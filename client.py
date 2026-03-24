from socket import *
import threading
import sys
import time
import json
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SIGNAL_HOST = "127.0.0.1"   # <- substitua pelo IP público do servidor
SIGNAL_TCP_PORT = 9005
SIGNAL_UDP_PORT = 9006

HOLE_PUNCH_ATTEMPTS = 10   # pacotes enviados durante o punch
HOLE_PUNCH_INTERVAL = 0.1  # segundos entre cada tentativa

# ── Criptografia ─────────────────────────────────────────────────────────────

def generate_keypair():
    """Gera um par de chaves X25519 (ECDH)."""
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_key, public_bytes


def derive_shared_key(private_key, peer_public_bytes):
    """Deriva uma chave AES-256 a partir do segredo ECDH compartilhado."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    peer_public_key = X25519PublicKey.from_public_bytes(peer_public_bytes)
    shared_secret = private_key.exchange(peer_public_key)
    # HKDF expande o segredo para 32 bytes (AES-256)
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"p2p-chat-v1",
    ).derive(shared_secret)
    return derived  # bytes — chave AES-GCM


def encrypt_message(aes_key: bytes, plaintext: str) -> bytes:
    """Cifra a mensagem com AES-256-GCM. Retorna nonce(12) + ciphertext."""
    nonce = os.urandom(12)
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return nonce + ciphertext


def decrypt_message(aes_key: bytes, data: bytes) -> str:
    """Decifra uma mensagem. Espera nonce(12) + ciphertext."""
    nonce, ciphertext = data[:12], data[12:]
    aesgcm = AESGCM(aes_key)
    return aesgcm.decrypt(nonce, ciphertext, None).decode()


# ── Escolha de sala ─────────────────────────────────────────────────────────

def choose_room():
    print("\n=== Chat P2P com Salas (E2E criptografado) ===")
    print("1. Criar sala")
    print("2. Entrar em sala")
    choice = input("Escolha (1/2): ").strip()
    room_name = input("Nome da sala: ").strip()
    password = input("Senha: ").strip()
    if choice == "1":
        return "CREATE", room_name, password
    elif choice == "2":
        return "JOIN", room_name, password
    else:
        print("Opção inválida.")
        sys.exit(1)


# ── Registro TCP ─────────────────────────────────────────────────────────────

def register(action, room_name, password, name, udp_port):
    """Registra no servidor (TCP) e retorna lista inicial de peers."""
    s = socket(AF_INET, SOCK_STREAM)
    s.connect((SIGNAL_HOST, SIGNAL_TCP_PORT))
    s.sendall(f"{action}:{room_name}:{password}:{name}:{udp_port}".encode())
    response = s.recv(4096).decode()
    s.close()

    if response.startswith("ERR:"):
        msgs = {
            "sala_ja_existe":   "Sala já existe. Use 'Entrar em sala'.",
            "sala_nao_existe":  "Sala não encontrada. Crie-a primeiro.",
            "senha_incorreta":  "Senha incorreta.",
            "formato_invalido": "Erro interno de protocolo.",
        }
        err = response.split(":", 1)[1]
        print(f"[ERRO] {msgs.get(err, err)}")
        sys.exit(1)

    peers = {}
    peers_raw = response[len("OK:"):]
    for entry in peers_raw.split(";"):
        if entry:
            n, ip, p = entry.split(":")
            peers[n] = {"ip": ip, "udp_port": int(p)}
    return peers


# ── Hole punching UDP ────────────────────────────────────────────────────────

def punch(udp_sock, targets):
    """Dispara pacotes para cada alvo a fim de abrir o NAT."""
    for _ in range(HOLE_PUNCH_ATTEMPTS):
        for ip, port in targets:
            try:
                udp_sock.sendto(b"PUNCH", (ip, port))
            except Exception:
                pass
        time.sleep(HOLE_PUNCH_INTERVAL)


def wait_for_peers(udp_sock, room_name, name, known_peers):
    """
    Envia READY ao servidor UDP e aguarda a lista completa de peers.
    Retorna dict { name: (ip, udp_port) }.
    """
    udp_sock.sendto(
        f"READY:{room_name}:{name}".encode(),
        (SIGNAL_HOST, SIGNAL_UDP_PORT)
    )
    print("[UDP] Aguardando confirmação de peers...")

    udp_sock.settimeout(60)
    while True:
        data, _ = udp_sock.recvfrom(4096)
        msg = data.decode()

        if msg.startswith("PEERS:"):
            peers = {}
            for entry in msg[len("PEERS:"):].split(";"):
                if entry:
                    n, ip, p = entry.split(":")
                    peers[n] = (ip, int(p))
            return peers

        if msg == "PUNCH":
            continue


# ── Troca de chaves públicas (ECDH) via UDP ──────────────────────────────────

def send_pubkey(udp_sock, my_name, my_pub_bytes, targets):
    """Envia a chave pública para uma lista de (ip, port)."""
    payload = f"PUBKEY:{my_name}:{my_pub_bytes.hex()}".encode()
    for ip, port in targets:
        try:
            udp_sock.sendto(payload, (ip, port))
        except Exception:
            pass


def exchange_keys(udp_sock, my_name, my_pub_bytes, peers):
    """
    Envia a chave pública para todos os peers e coleta as deles.
    Retorna dict { peer_name: bytes(public_key) }.
    """
    peer_keys = {}
    expected = set(peers.keys())

    send_pubkey(udp_sock, my_name, my_pub_bytes, list(peers.values()))

    udp_sock.settimeout(30)
    while set(peer_keys.keys()) < expected:
        try:
            data, _ = udp_sock.recvfrom(4096)
            raw = data.decode()
        except timeout:
            missing = expected - set(peer_keys.keys())
            for peer_name in missing:
                send_pubkey(udp_sock, my_name, my_pub_bytes, [peers[peer_name]])
            continue

        if raw.startswith("PUBKEY:"):
            parts = raw.split(":", 2)
            if len(parts) == 3:
                _, sender, hex_key = parts
                if sender in expected and sender not in peer_keys:
                    peer_keys[sender] = bytes.fromhex(hex_key)
                    print(f"[CRYPTO] Chave pública recebida de '{sender}'")

    return peer_keys


# ── Recepção e envio de mensagens UDP ────────────────────────────────────────

def receive_udp(udp_sock, my_name, my_pub_bytes, private_key, peers, peer_aes_keys):
    """
    Recebe mensagens e tambem lida com novos peers que entram depois.
    - peers:         dict { name: (ip, port) }  - atualizado em tempo real
    - peer_aes_keys: dict { name: bytes }        - atualizado em tempo real
    """
    udp_sock.settimeout(None)
    while True:
        try:
            data, addr = udp_sock.recvfrom(65535)
            raw = data.decode(errors="replace")

            if raw in ("PUNCH", ""):
                continue

            # Servidor avisou sobre novos peers na sala
            if raw.startswith("PEERS:"):
                for entry in raw[len("PEERS:"):].split(";"):
                    if not entry:
                        continue
                    n, ip, p = entry.split(":")
                    if n != my_name and n not in peers:
                        peers[n] = (ip, int(p))
                        print(f"[+] Novo peer detectado: {n} — enviando chave publica")
                        send_pubkey(udp_sock, my_name, my_pub_bytes, [(ip, int(p))])
                continue

            # Novo peer enviando chave publica
            if raw.startswith("PUBKEY:"):
                parts = raw.split(":", 2)
                if len(parts) == 3:
                    _, sender, hex_key = parts
                    if sender not in peer_aes_keys:
                        pub_bytes = bytes.fromhex(hex_key)
                        peer_aes_keys[sender] = derive_shared_key(private_key, pub_bytes)
                        print(f"[CRYPTO] Chave derivada para novo peer '{sender}' OK")
                        if sender in peers:
                            send_pubkey(udp_sock, my_name, my_pub_bytes, [peers[sender]])
                continue

            # Formato: CMSG:<nome>:<hex(nonce+ciphertext)>
            if raw.startswith("CMSG:"):
                parts = raw.split(":", 2)
                if len(parts) != 3:
                    continue
                _, sender, hex_payload = parts

                aes_key = peer_aes_keys.get(sender)
                if not aes_key:
                    print(f"[!] Mensagem de '{sender}' sem chave — ignorada.")
                    continue

                print(f"[CRYPTO] Cifrado ({sender}): {hex_payload[:48]}...")
                try:
                    plaintext = decrypt_message(aes_key, bytes.fromhex(hex_payload))
                    print(f"[CRYPTO] Decifrado ok: {plaintext[:60]}")
                    msg = json.loads(plaintext)
                except Exception as e:
                    print(f"[!] Falha ao decifrar de '{sender}':", e)
                    continue

                if msg.get("type") == "message":
                    print(f"\n[{msg['from']}] {msg['content']}\nVoce: ", end="", flush=True)

        except Exception as e:
            print(f"\n[!] Erro ao receber: {e}")
            break
def broadcast_udp(udp_sock, peers, name, peer_aes_keys):
    """Lê do terminal, cifra e envia para todos os peers via UDP."""
    while True:
        msg = input("Você: ")

        data = json.dumps({
            "type": "message",
            "from": name,
            "content": msg
        })

        for peer_name, (ip, port) in peers.items():
            aes_key = peer_aes_keys.get(peer_name)
            if not aes_key:
                print(f"[!] Sem chave para '{peer_name}' — mensagem não enviada.")
                continue
            try:
                encrypted = encrypt_message(aes_key, data)
                payload = f"CMSG:{name}:{encrypted.hex()}".encode()
                udp_sock.sendto(payload, (ip, port))
            except Exception as e:
                print(f"[!] Falha ao enviar para {peer_name}: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 3:
        print("Uso: python client.py <nome> <porta_udp_local>")
        sys.exit(1)

    name = sys.argv[1]
    local_udp_port = int(sys.argv[2])

    # Gera par de chaves ECDH logo na inicialização
    private_key, my_pub_bytes = generate_keypair()
    print(f"[CRYPTO] Par de chaves X25519 gerado.")

    # Cria o socket UDP
    udp_sock = socket(AF_INET, SOCK_DGRAM)
    udp_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    udp_sock.bind(("0.0.0.0", local_udp_port))
    print(f"[{name}] Socket UDP aberto na porta {local_udp_port}")

    action, room_name, password = choose_room()

    # Registro TCP
    initial_peers = register(action, room_name, password, name, local_udp_port)
    verb = "criada" if action == "CREATE" else "entrou"
    print(f"[OK] Sala '{room_name}' {verb}.")

    # Fase de hole punching
    peers = wait_for_peers(udp_sock, room_name, name, initial_peers)
    print(f"[+] Peers encontrados: {list(peers.keys())}")

    targets = list(peers.values())
    print(f"[*] Iniciando hole punch para {targets}...")
    threading.Thread(target=punch, args=(udp_sock, targets), daemon=True).start()

    time.sleep(HOLE_PUNCH_ATTEMPTS * HOLE_PUNCH_INTERVAL + 0.5)
    print("[+] Hole punch concluído.")

    # ── Troca de chaves públicas (ECDH) ──────────────────────────────────────
    print("[CRYPTO] Trocando chaves públicas com peers...")
    peer_pub_keys = exchange_keys(udp_sock, name, my_pub_bytes, peers)

    # Deriva uma chave AES-GCM por peer
    peer_aes_keys = {}
    for peer_name, pub_bytes in peer_pub_keys.items():
        peer_aes_keys[peer_name] = derive_shared_key(private_key, pub_bytes)
        print(f"[CRYPTO] Chave AES-256 derivada para '{peer_name}' ✓")

    print("[+] Canal E2E criptografado estabelecido. Pode começar a conversar!\n")

    # Inicia recepção em background
    threading.Thread(
        target=receive_udp, args=(udp_sock, name, my_pub_bytes, private_key, peers, peer_aes_keys), daemon=True
    ).start()

    # Envio de mensagens para todos
    broadcast_udp(udp_sock, peers, name, peer_aes_keys)


main()