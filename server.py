from socket import *
import threading

# rooms[room_name] = {
#   "password": str,
#   "peers": { name: {"ip": str, "udp_port": int, "ready": bool} }
# }
rooms = {}
lock  = threading.Lock()

TCP_PORT = 9005
UDP_PORT = 9006

# Socket UDP global (usado também para notificar peers já conectados)
udp_sock = None


def broadcast_peers(room_name):
    """
    Envia a lista atualizada de peers para TODOS os membros da sala,
    inclusive os que já estavam conectados.
    Deve ser chamado dentro do lock.
    """
    peers = rooms[room_name]["peers"]
    for peer_name, peer_info in peers.items():
        if not peer_info["ready"]:
            continue
        others = ";".join(
            f"{n}:{info['ip']}:{info['udp_port']}"
            for n, info in peers.items()
            if n != peer_name
        )
        dest = (peer_info["ip"], peer_info["udp_port"])
        try:
            udp_sock.sendto(f"PEERS:{others}".encode(), dest)
        except Exception as e:
            print(f"[UDP] Erro ao notificar {peer_name}: {e}")


# ── Servidor TCP: criação e entrada em salas ─────────────────────────────────

def handle_tcp(conn, addr):
    try:
        data = conn.recv(4096).decode().strip()
        parts = data.split(":")
        if len(parts) != 5:
            conn.sendall("ERR:formato_invalido".encode())
            return

        action, room_name, password, name, udp_port_str = parts

        with lock:
            if action == "CREATE":
                if room_name in rooms:
                    conn.sendall("ERR:sala_ja_existe".encode())
                    return
                rooms[room_name] = {"password": password, "peers": {}}

            if action in ("CREATE", "JOIN"):
                if room_name not in rooms:
                    conn.sendall("ERR:sala_nao_existe".encode())
                    return
                if rooms[room_name]["password"] != password:
                    conn.sendall("ERR:senha_incorreta".encode())
                    return

                rooms[room_name]["peers"][name] = {
                    "ip":       addr[0],
                    "udp_port": int(udp_port_str),
                    "ready":    False,
                }

                peers = rooms[room_name]["peers"]
                other_peers = ";".join(
                    f"{n}:{info['ip']}:{info['udp_port']}"
                    for n, info in peers.items()
                    if n != name
                )
                conn.sendall(f"OK:{other_peers}".encode())
            else:
                conn.sendall("ERR:acao_desconhecida".encode())
    except Exception as e:
        print(f"[TCP] Erro: {e}")
    finally:
        conn.close()


# ── Servidor UDP: coordena o hole punching ────────────────────────────────────
#
# Correção principal: quando um novo peer envia READY, o servidor
# notifica TODOS os peers já prontos na sala com a lista atualizada —
# não apenas quando "todos" ficam prontos ao mesmo tempo.
# Isso permite que um terceiro (ou quarto) peer entre depois.

def udp_server():
    global udp_sock
    udp_sock = socket(AF_INET, SOCK_DGRAM)
    udp_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    udp_sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[UDP] Escutando na porta {UDP_PORT}...")

    while True:
        try:
            data, addr = udp_sock.recvfrom(1024)
            msg = data.decode().strip()

            if not msg.startswith("READY:"):
                continue

            parts = msg.split(":", 2)
            if len(parts) != 3:
                continue
            _, room_name, name = parts

            with lock:
                if room_name not in rooms or name not in rooms[room_name]["peers"]:
                    continue

                peer = rooms[room_name]["peers"][name]
                peer["ip"]       = addr[0]
                peer["udp_port"] = addr[1]
                peer["ready"]    = True

                ready_peers = {
                    n: info for n, info in rooms[room_name]["peers"].items()
                    if info["ready"]
                }

                # Só dispara se há pelo menos 2 peers prontos
                if len(ready_peers) >= 2:
                    broadcast_peers(room_name)
                    print(f"[UDP] Lista enviada para {list(ready_peers.keys())} — sala '{room_name}'")

        except Exception as e:
            print(f"[UDP] Erro: {e}")


# ── Inicialização ─────────────────────────────────────────────────────────────

threading.Thread(target=udp_server, daemon=True).start()

tcp_server = socket(AF_INET, SOCK_STREAM)
tcp_server.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
tcp_server.bind(("0.0.0.0", TCP_PORT))
tcp_server.listen()
print(f"[TCP] Servidor de sinalização escutando na porta {TCP_PORT}...")

while True:
    conn, addr = tcp_server.accept()
    threading.Thread(target=handle_tcp, args=(conn, addr), daemon=True).start()