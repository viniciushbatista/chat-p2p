import tkinter as tk
from tkinter import scrolledtext
from socket import *
import threading
import time
import json
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SIGNAL_HOST     = "127.0.0.1"
SIGNAL_TCP_PORT = 9005
SIGNAL_UDP_PORT = 9006
HOLE_PUNCH_ATTEMPTS = 10
HOLE_PUNCH_INTERVAL = 0.1

BG      = "#1e1e2e"
BG2     = "#2a2a3e"
BG3     = "#313147"
ACCENT  = "#7c6af7"
ACCENT2 = "#5a4ed1"
GREEN   = "#50fa7b"
TEXT    = "#cdd6f4"
TEXT2   = "#a6adc8"

def generate_keypair():
    priv = X25519PrivateKey.generate()
    pub  = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv, pub

def derive_shared_key(private_key, peer_pub_bytes):
    peer_pub = X25519PublicKey.from_public_bytes(peer_pub_bytes)
    secret   = private_key.exchange(peer_pub)
    return HKDF(algorithm=hashes.SHA256(), length=32,
                salt=None, info=b"p2p-chat-v1").derive(secret)

def encrypt_message(key, plaintext):
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), None)

def decrypt_message(key, data):
    return AESGCM(key).decrypt(data[:12], data[12:], None).decode()

def tcp_register(action, room, password, name, udp_port):
    s = socket(AF_INET, SOCK_STREAM)
    s.connect((SIGNAL_HOST, SIGNAL_TCP_PORT))
    s.sendall(f"{action}:{room}:{password}:{name}:{udp_port}".encode())
    resp = s.recv(4096).decode()
    s.close()
    if resp.startswith("ERR:"):
        raise RuntimeError({
            "sala_ja_existe":  "Sala já existe. Use 'Entrar'.",
            "sala_nao_existe": "Sala não encontrada. Crie-a primeiro.",
            "senha_incorreta": "Senha incorreta.",
        }.get(resp.split(":", 1)[1], resp))
    peers = {}
    for e in resp[len("OK:"):].split(";"):
        if e:
            n, ip, p = e.split(":")
            peers[n] = (ip, int(p))
    return peers

def udp_wait_peers(sock, room, name):
    sock.sendto(f"READY:{room}:{name}".encode(), (SIGNAL_HOST, SIGNAL_UDP_PORT))
    sock.settimeout(60)
    while True:
        data, _ = sock.recvfrom(4096)
        msg = data.decode()
        if msg.startswith("PEERS:"):
            peers = {}
            for e in msg[len("PEERS:"):].split(";"):
                if e:
                    n, ip, p = e.split(":")
                    peers[n] = (ip, int(p))
            return peers

def do_punch(sock, targets):
    for _ in range(HOLE_PUNCH_ATTEMPTS):
        for ip, port in targets:
            try: sock.sendto(b"PUNCH", (ip, port))
            except: pass
        time.sleep(HOLE_PUNCH_INTERVAL)

def send_pubkey(sock, my_name, my_pub, targets):
    payload = f"PUBKEY:{my_name}:{my_pub.hex()}".encode()
    for ip, port in targets:
        try: sock.sendto(payload, (ip, port))
        except: pass


class ChatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("P2P Chat · E2E Criptografado")
        self.geometry("820x580")
        self.minsize(680, 460)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.udp_sock  = None
        self.peers     = {}
        self.peer_aes  = {}
        self.my_name   = ""
        self.my_pub    = None
        self.priv_key  = None
        self._peer_rows = {}

        self._show_login()

    # ── Login ─────────────────────────────────────────────────────────────────

    def _show_login(self):
        self.login_frame = tk.Frame(self, bg=BG)
        self.login_frame.place(relx=.5, rely=.5, anchor="center")

        tk.Label(self.login_frame, text="🔒  P2P Chat",
                 font=("Helvetica", 22, "bold"), bg=BG, fg=ACCENT
                 ).grid(row=0, column=0, columnspan=2, pady=(0, 6))
        tk.Label(self.login_frame, text="Criptografia E2E · X25519 + AES-256-GCM",
                 font=("Helvetica", 9), bg=BG, fg=TEXT2
                 ).grid(row=1, column=0, columnspan=2, pady=(0, 20))

        self._vars = {}
        for i, (label, key) in enumerate([("Seu nome", "name"), ("Porta UDP", "port"),
                                           ("Nome da sala", "room"), ("Senha", "pwd")]):
            tk.Label(self.login_frame, text=label, bg=BG, fg=TEXT2,
                     font=("Helvetica", 10)
                     ).grid(row=i+2, column=0, sticky="e", padx=(0, 10), pady=5)
            v = tk.StringVar()
            self._vars[key] = v
            tk.Entry(self.login_frame, textvariable=v,
                     show="*" if key == "pwd" else "",
                     bg=BG3, fg=TEXT, insertbackground=TEXT,
                     relief="flat", font=("Helvetica", 11), width=22,
                     highlightthickness=1, highlightcolor=ACCENT,
                     highlightbackground=BG2
                     ).grid(row=i+2, column=1, pady=5, ipady=4)
        self._vars["port"].set("5001")

        btn_frame = tk.Frame(self.login_frame, bg=BG)
        btn_frame.grid(row=7, column=0, columnspan=2, pady=20)
        tk.Button(btn_frame, text="Criar sala", width=12,
                  bg=ACCENT, fg="white", relief="flat", cursor="hand2",
                  font=("Helvetica", 10, "bold"), activebackground=ACCENT2,
                  command=lambda: self._connect("CREATE")
                  ).pack(side="left", padx=6, ipady=6)
        tk.Button(btn_frame, text="Entrar na sala", width=12,
                  bg=BG3, fg=TEXT, relief="flat", cursor="hand2",
                  font=("Helvetica", 10), activebackground=BG2,
                  command=lambda: self._connect("JOIN")
                  ).pack(side="left", padx=6, ipady=6)

        self._status_var = tk.StringVar(value="")
        tk.Label(self.login_frame, textvariable=self._status_var,
                 bg=BG, fg=TEXT2, font=("Helvetica", 9), wraplength=320
                 ).grid(row=8, column=0, columnspan=2)

    def _connect(self, action):
        name     = self._vars["name"].get().strip()
        room     = self._vars["room"].get().strip()
        pwd      = self._vars["pwd"].get().strip()
        port_str = self._vars["port"].get().strip()
        if not all([name, room, pwd, port_str]):
            self._status_var.set("⚠ Preencha todos os campos.")
            return
        try:
            port = int(port_str)
        except ValueError:
            self._status_var.set("⚠ Porta inválida.")
            return
        self.my_name = name
        self._set_status("Conectando…")
        threading.Thread(target=self._bg_connect,
                         args=(action, name, room, pwd, port), daemon=True).start()

    def _bg_connect(self, action, name, room, pwd, port):
        try:
            self._set_status("Gerando chaves criptográficas…")
            self.priv_key, self.my_pub = generate_keypair()

            self._set_status("Abrindo socket UDP…")
            self.udp_sock = socket(AF_INET, SOCK_DGRAM)
            self.udp_sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            self.udp_sock.bind(("0.0.0.0", port))

            self._set_status("Registrando no servidor…")
            tcp_register(action, room, pwd, name, port)

            self._set_status("Aguardando peers…")
            peers = udp_wait_peers(self.udp_sock, room, name)
            self.peers = peers

            self._set_status("Realizando hole punch…")
            threading.Thread(target=do_punch,
                             args=(self.udp_sock, list(peers.values())),
                             daemon=True).start()
            time.sleep(HOLE_PUNCH_ATTEMPTS * HOLE_PUNCH_INTERVAL + 0.5)

            # Envia a chave pública para quem já está na sala.
            # Quem entrar depois será tratado no _receive_loop.
            if peers:
                send_pubkey(self.udp_sock, name, self.my_pub, list(peers.values()))

            # Abre o chat sem esperar as respostas — a troca termina de forma assíncrona
            self.after(0, self._show_chat, room)

        except Exception as e:
            self.after(0, lambda err=e: self._set_status(f"Erro: {err}"))

    def _set_status(self, msg):
        self.after(0, lambda m=msg: self._status_var.set(m))

    # ── Chat ──────────────────────────────────────────────────────────────────

    def _show_chat(self, room):
        self.login_frame.destroy()
        self.title(f"P2P Chat · {room}")

        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True)

        sidebar = tk.Frame(main, bg=BG2, width=180)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="Sala", bg=BG2, fg=TEXT2,
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=12, pady=(14, 2))
        tk.Label(sidebar, text=f"  {room}", bg=BG2, fg=TEXT,
                 font=("Helvetica", 11, "bold")).pack(anchor="w", padx=12)
        tk.Frame(sidebar, bg=BG3, height=1).pack(fill="x", padx=12, pady=10)
        tk.Label(sidebar, text="Peers conectados", bg=BG2, fg=TEXT2,
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=12, pady=(0, 6))

        self.peers_frame = tk.Frame(sidebar, bg=BG2)
        self.peers_frame.pack(fill="x", padx=8)

        self._add_peer_row(self.my_name, is_me=True)
        for pname in self.peers:
            self._add_peer_row(pname)

        tk.Frame(sidebar, bg=BG3, height=1).pack(fill="x", padx=12, pady=10)
        tk.Label(sidebar, text="🔒 E2E Ativo\nX25519 + AES-256-GCM",
                 bg=BG2, fg=GREEN, font=("Helvetica", 9), justify="left"
                 ).pack(anchor="w", padx=14, pady=(0, 12))

        chat_area = tk.Frame(main, bg=BG)
        chat_area.pack(side="left", fill="both", expand=True)

        header = tk.Frame(chat_area, bg=BG2, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=f"#{room}", bg=BG2, fg=TEXT,
                 font=("Helvetica", 13, "bold")).pack(side="left", padx=16, pady=12)
        tk.Label(header, text=f"Você: {self.my_name}", bg=BG2, fg=TEXT2,
                 font=("Helvetica", 9)).pack(side="right", padx=16)

        self.chat_box = scrolledtext.ScrolledText(
            chat_area, state="disabled", wrap="word",
            bg=BG, fg=TEXT, font=("Helvetica", 11),
            relief="flat", padx=16, pady=12, selectbackground=ACCENT2)
        self.chat_box.pack(fill="both", expand=True)
        self.chat_box.tag_config("me",        foreground=TEXT,   justify="right")
        self.chat_box.tag_config("me_name",   foreground=ACCENT, justify="right",
                                  font=("Helvetica", 9, "bold"))
        self.chat_box.tag_config("them",      foreground=TEXT,   justify="left")
        self.chat_box.tag_config("them_name", foreground=GREEN,  justify="left",
                                  font=("Helvetica", 9, "bold"))
        self.chat_box.tag_config("system",    foreground=TEXT2,  justify="center",
                                  font=("Helvetica", 9, "italic"))

        self._append_msg("Sistema",
                         "Conectado — aguardando troca de chaves com peers…", "system")

        input_bar = tk.Frame(chat_area, bg=BG2, height=54)
        input_bar.pack(fill="x", side="bottom")
        input_bar.pack_propagate(False)

        self.msg_var = tk.StringVar()
        self.msg_entry = tk.Entry(
            input_bar, textvariable=self.msg_var,
            bg=BG3, fg=TEXT, insertbackground=TEXT,
            relief="flat", font=("Helvetica", 11),
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BG2)
        self.msg_entry.pack(side="left", fill="both", expand=True,
                             padx=(12, 6), pady=10, ipady=5)
        self.msg_entry.bind("<Return>", lambda e: self._send())

        tk.Button(input_bar, text="Enviar", bg=ACCENT, fg="white",
                  relief="flat", cursor="hand2",
                  font=("Helvetica", 10, "bold"), activebackground=ACCENT2,
                  command=self._send
                  ).pack(side="right", padx=(0, 12), pady=10, ipadx=12, ipady=5)

        self.msg_entry.focus()
        threading.Thread(target=self._receive_loop, daemon=True).start()

    def _add_peer_row(self, name, is_me=False):
        if name in self._peer_rows:
            return
        row = tk.Frame(self.peers_frame, bg=BG2)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="●", bg=BG2, fg=ACCENT if is_me else GREEN,
                 font=("Helvetica", 8)).pack(side="left", padx=(4, 4))
        tk.Label(row, text=name + (" (você)" if is_me else ""), bg=BG2, fg=TEXT,
                 font=("Helvetica", 10)).pack(side="left")
        self._peer_rows[name] = row

    def _append_msg(self, sender, content, tag):
        self.chat_box.config(state="normal")
        if tag == "system":
            self.chat_box.insert("end", f"\n  {content}\n", "system")
        elif tag == "me":
            self.chat_box.insert("end", f"\n{sender}  \n", "me_name")
            self.chat_box.insert("end", f"{content}\n", "me")
        else:
            self.chat_box.insert("end", f"\n{sender}\n", "them_name")
            self.chat_box.insert("end", f"{content}\n", "them")
        self.chat_box.config(state="disabled")
        self.chat_box.see("end")

    def _send(self):
        content = self.msg_var.get().strip()
        if not content:
            return
        self.msg_var.set("")
        data = json.dumps({"type": "message", "from": self.my_name, "content": content})
        sent = False
        for pname, (ip, port) in list(self.peers.items()):
            key = self.peer_aes.get(pname)
            if not key:
                continue
            try:
                enc = encrypt_message(key, data)
                self.udp_sock.sendto(
                    f"CMSG:{self.my_name}:{enc.hex()}".encode(), (ip, port))
                sent = True
            except Exception as e:
                self.after(0, lambda err=e, p=pname:
                    self._append_msg("Sistema", f"Erro ao enviar para {p}: {err}", "system"))
        if sent:
            self._append_msg(self.my_name, content, "me")
        elif not self.peer_aes:
            self._append_msg("Sistema", "Aguardando troca de chaves com os peers…", "system")

    # ── Loop de recepção ──────────────────────────────────────────────────────

    def _receive_loop(self):
        self.udp_sock.settimeout(None)
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(65535)
                raw = data.decode(errors="replace")

                if raw in ("PUNCH", ""):
                    continue

                # Servidor notificou peers novos ou atualizados
                if raw.startswith("PEERS:"):
                    new_peers = []
                    for entry in raw[len("PEERS:"):].split(";"):
                        if not entry:
                            continue
                        n, ip, p = entry.split(":")
                        if n != self.my_name and n not in self.peers:
                            self.peers[n] = (ip, int(p))
                            new_peers.append((n, ip, int(p)))
                    for n, ip, p in new_peers:
                        self.after(0, self._add_peer_row, n)
                        self.after(0, self._append_msg, "Sistema",
                                   f"{n} entrou na sala.", "system")
                        send_pubkey(self.udp_sock, self.my_name, self.my_pub, [(ip, p)])
                    continue

                # Recebeu chave pública de um peer
                if raw.startswith("PUBKEY:"):
                    parts = raw.split(":", 2)
                    if len(parts) != 3:
                        continue
                    _, sender, hex_key = parts
                    if sender != self.my_name and sender not in self.peer_aes:
                        try:
                            self.peer_aes[sender] = derive_shared_key(
                                self.priv_key, bytes.fromhex(hex_key))
                        except Exception:
                            continue
                        # Registra o peer caso não esteja no dicionário ainda
                        if sender not in self.peers:
                            self.peers[sender] = (addr[0], addr[1])
                        # Responde com a própria chave pública
                        send_pubkey(self.udp_sock, self.my_name,
                                    self.my_pub, [self.peers[sender]])
                        self.after(0, self._add_peer_row, sender)
                        self.after(0, self._append_msg, "Sistema",
                                   f"🔒 Canal cifrado com {sender} estabelecido.", "system")
                    continue

                # Mensagem cifrada
                if raw.startswith("CMSG:"):
                    parts = raw.split(":", 2)
                    if len(parts) != 3:
                        continue
                    _, sender, hex_pay = parts
                    key = self.peer_aes.get(sender)
                    if not key:
                        continue
                    try:
                        plaintext = decrypt_message(key, bytes.fromhex(hex_pay))
                        msg = json.loads(plaintext)
                    except Exception:
                        continue
                    if msg.get("type") == "message":
                        self.after(0, lambda m=msg: self._append_msg(
                            m["from"], m["content"], "them"))

            except Exception:
                break


if __name__ == "__main__":
    app = ChatApp()
    app.mainloop()