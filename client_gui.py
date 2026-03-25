import tkinter as tk
from tkinter import messagebox, simpledialog
import threading
import socket
import time
import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# Paleta do Tkinter
BG       = "#0f1117"
BG2      = "#1a1d27"
BG3      = "#252836"
ACCENT   = "#7c6af7"
ACCENT2  = "#5c4fd6"
FG       = "#e8e8f0"
FG2      = "#9090a8"
SUCCESS  = "#4caf82"
DANGER   = "#e05c5c"
BORDER   = "#2e3148"

FONT_MONO = ("Courier", 10)
FONT_UI   = ("Helvetica", 10)
FONT_BIG  = ("Helvetica", 16, "bold")
FONT_MED  = ("Helvetica", 11, "bold")

PEER_PORT = 9100                    # porta base do listener, incrementada se ocupada

SALT = b"p2p-chat-salt-2025"         # fixo para todos os peers derivarem a mesma chave

# Criptografia (Retirado de um exemplo no site da biblioteca cryptography)
# Gera uma chave usando o algoritmo PBKDF2HMAC
def derive_key(password: str) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,          # Tamanho da senha
        salt=SALT,
        iterations=200_000, # Executa a função de criptografia por 200k iterações
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

# Criptografa a senha após criar um objeto fernet usando a chave derivada na função derive_key.
def encrypt(fernet: Fernet, text: str) -> bytes:
    return fernet.encrypt(text.encode())

# Decifra uma mensagem criptografada, utilizando a mensagem e o mesmo objeto fernet utilizado na criptografia.
def decrypt(fernet: Fernet, token: bytes) -> str:
    return fernet.decrypt(token).decode()

# Comunicação com servidor de sinalização
# Realiza a conexão com o servidor de sinalização, conforma o IP fornecido pelo usuário e a porta 9005 (padrão)
def tcp_connect(host: str, port: int, timeout: float = 5) -> socket.socket:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM) # Obtém todos os endereços TCP possíveis
    last_err = Exception("sem endereço resolvido")
    for af, socktype, proto, canonname, sockaddr in infos:
        try:
            s = socket.socket(af, socktype, proto)
            s.settimeout(timeout)
            s.connect(sockaddr)
            return s
        except OSError as e:
            last_err = e
            try: s.close()
            except: pass
    raise last_err

# Envia e aguarda resposta de uma requisição para o servidor de sinalização 
def sig_send(server_ip: str, server_port: int, message: str) -> str:
    with tcp_connect(server_ip, server_port) as s:
        s.sendall(message.encode())
        return s.recv(4096).decode().strip()

# Listener P2P (usuário)
class PeerListener:
    def __init__(self, port: int, fernet: Fernet, on_message):
        self.port       = port
        self.fernet     = fernet
        self.on_message = on_message
        self._stop      = threading.Event()
        self._srv       = None

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._stop.set()
        if self._srv:
            try: self._srv.close()
            except: pass

    def _run(self):
        try:
            self._srv = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            self._srv.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._srv.bind(("", self.port))
        except OSError:
            self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._srv.bind(("0.0.0.0", self.port))
        self._srv.listen()
        self._srv.settimeout(1)
        while not self._stop.is_set():
            try:
                conn, addr = self._srv.accept()
                threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except: break

    def _handle(self, conn, addr):
        try:
            data = conn.recv(8192)
            if data:
                print(f"\n[TESTE CRIPTOGRAFIA - ENTRADA]") #teste criptografia
                print(f"Dados brutos recebidos: {data}")#teste criptografia

                text = decrypt(self.fernet, data)

                print(f"Texto após Descriptografar: {text}")#teste criptografia
                print("-" * 30)#teste criptografia

                self.on_message(text)
        except Exception as e:
            self.on_message(f"[erro ao receber mensagem: {e}]")
        finally:
            conn.close()

# Broadcast P2P

def broadcast(peers: dict, fernet: Fernet, text: str, my_name: str):
    token = encrypt(fernet, text)

    print("\n[TESTE CRIPTOGRAFIA - SAÍDA]") #teste criptografia
    print(f"Mensagem Original: {text}") #teste criptografia
    print(f"Mensagem Criptografada (Bytes): {token}") #teste criptografia
    print("-" * 30) #teste criptografia

    for name, info in list(peers.items()):
        if name == my_name:
            continue
        try:
            with tcp_connect(info["ip"], info["tcp_port"], timeout=3) as s:
                s.sendall(token)
        except Exception as e:
            print(f"[broadcast] falha ao enviar para {name}: {e}")

# ── Helpers de widget ──────────────────────────────────────────────────────────

def styled_entry(parent, **kwargs):
    e = tk.Entry(
        parent,
        bg=BG3, fg=FG, insertbackground=FG,
        relief="flat", bd=0,
        font=FONT_UI,
        highlightthickness=1,
        highlightcolor=ACCENT,
        highlightbackground=BORDER,
        **kwargs
    )
    return e

def styled_button(parent, text, command, color=ACCENT, fg=FG, **kwargs):
    b = tk.Button(
        parent, text=text, command=command,
        bg=color, fg=fg,
        activebackground=ACCENT2, activeforeground=FG,
        relief="flat", bd=0, cursor="hand2",
        font=("Helvetica", 10, "bold"),
        padx=16, pady=8,
        **kwargs
    )
    return b

def label(parent, text, font=FONT_UI, fg=FG, **kwargs):
    return tk.Label(parent, text=text, bg=BG, fg=fg, font=font, **kwargs)

def frame(parent, bg=BG, **kwargs):
    return tk.Frame(parent, bg=bg, **kwargs)

# Telas
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("P2P Chat")
        self.geometry("520x420")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._center()

        # estado compartilhado
        self.server_ip    = ""
        self.server_port  = 9005
        self.my_name      = ""
        self.my_port      = PEER_PORT
        self.room_name    = ""
        self.room_password= ""
        self.fernet       = None
        self.peers        = {}      # {name: {ip, tcp_port}}
        self.listener     = None
        self._poll_active = False   # controla polling de peers

        self._current_frame = None
        self.show_connect()

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _switch(self, new_frame):
        if self._current_frame:
            self._current_frame.destroy()
        self._current_frame = new_frame
        new_frame.pack(fill="both", expand=True)

    # Tela 1: conexão

    def show_connect(self):
        f = frame(self)

        # logo
        tk.Label(f, text="◈ p2p chat", bg=BG, fg=ACCENT,
                 font=("Courier", 22, "bold")).pack(pady=(48, 4))
        tk.Label(f, text="servidor de sinalização", bg=BG, fg=FG2,
                 font=("Courier", 9)).pack(pady=(0, 32))

        inner = frame(f, bg=BG2)
        inner.pack(padx=60, fill="x")
        inner.configure(highlightthickness=1, highlightbackground=BORDER)

        pad = frame(inner, bg=BG2)
        pad.pack(padx=20, pady=20, fill="x")

        tk.Label(pad, text="IP do servidor", bg=BG2, fg=FG2,
                 font=("Helvetica", 9)).pack(anchor="w")
        ip_var = tk.StringVar(value="127.0.0.1")
        ip_e = styled_entry(pad, textvariable=ip_var)
        ip_e.pack(fill="x", pady=(2, 12), ipady=6)

        tk.Label(pad, text="Seu nome", bg=BG2, fg=FG2,
                 font=("Helvetica", 9)).pack(anchor="w")
        name_var = tk.StringVar()
        name_e = styled_entry(pad, textvariable=name_var)
        name_e.pack(fill="x", pady=(2, 16), ipady=6)

        status_lbl = tk.Label(pad, text="", bg=BG2, fg=DANGER, font=("Helvetica", 9))
        status_lbl.pack()

        def connect():
            ip   = ip_var.get().strip()
            name = name_var.get().strip()
            if not ip or not name:
                status_lbl.config(text="Preencha todos os campos.")
                return
            status_lbl.config(text="Conectando...", fg=FG2)
            self.update()
            try:
                resp = sig_send(ip, self.server_port, "LIST")
            except Exception as e:
                status_lbl.config(text=f"Erro: {e}", fg=DANGER)
                return
            self.server_ip = ip
            self.my_name   = name
            status_lbl.config(text="OK!", fg=SUCCESS)
            self.after(300, lambda: self.show_lobby(resp))

        btn = styled_button(pad, "Conectar →", connect)
        btn.pack(fill="x", pady=(8, 0))

        ip_e.bind("<Return>", lambda e: name_e.focus())
        name_e.bind("<Return>", lambda e: connect())

        self._switch(f)
        ip_e.focus()

    # Tela 2: lobby

    def show_lobby(self, rooms_resp=""):
        self.geometry("680x500")
        self._center()
        f = frame(self)

        # cabeçalho
        hdr = frame(f, bg=BG2)
        hdr.pack(fill="x")
        hdr.configure(highlightthickness=1, highlightbackground=BORDER)
        hdr_pad = frame(hdr, bg=BG2)
        hdr_pad.pack(padx=20, pady=12, fill="x", side="left")
        tk.Label(hdr_pad, text="◈ p2p chat", bg=BG2, fg=ACCENT,
                 font=("Courier", 13, "bold")).pack(side="left")
        tk.Label(hdr_pad, text=f"  —  {self.my_name}", bg=BG2, fg=FG2,
                 font=("Courier", 10)).pack(side="left")

        btn_new = styled_button(hdr, "＋ Nova sala", self._create_room_dialog,
                                color=BG3)
        btn_new.pack(side="right", padx=16, pady=10)

        btn_ref = styled_button(hdr, "↺", self._refresh_lobby, color=BG3, width=3)
        btn_ref.pack(side="right", pady=10)

        # lista
        body = frame(f)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(body, text="SALAS DISPONÍVEIS", bg=BG, fg=FG2,
                 font=("Courier", 8)).pack(anchor="w", pady=(0, 8))

        list_frame = frame(body, bg=BG2)
        list_frame.pack(fill="both", expand=True)
        list_frame.configure(highlightthickness=1, highlightbackground=BORDER)

        canvas = tk.Canvas(list_frame, bg=BG2, bd=0, highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical",
                                 command=canvas.yview, bg=BG3)
        inner = frame(canvas, bg=BG2)

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._lobby_inner  = inner
        self._lobby_canvas = canvas
        self._lobby_frame  = f

        self._populate_rooms(inner, rooms_resp)
        self._switch(f)

    def _populate_rooms(self, inner, rooms_resp):
        for w in inner.winfo_children():
            w.destroy()

        # parse "ROOMS|sala|qtd;sala|qtd"
        rooms = []
        if rooms_resp.startswith("ROOMS|"):
            payload = rooms_resp[6:]
            if payload:
                for entry in payload.split(";"):
                    parts = entry.split("|")
                    if len(parts) == 2:
                        rooms.append((parts[0], parts[1]))

        if not rooms:
            tk.Label(inner, text="\nNenhuma sala disponível.\nCrie uma nova!",
                     bg=BG2, fg=FG2, font=FONT_UI).pack(pady=20)
            return

        for name, count in rooms:
            row = frame(inner, bg=BG2)
            row.pack(fill="x", padx=0)
            row.configure(highlightthickness=0)

            sep = frame(inner, bg=BORDER, height=1)
            sep.pack(fill="x")

            def make_enter(n=name):
                return lambda e=None: self._join_room_dialog(n)

            row_btn = tk.Button(
                row, text=f"  {name}",
                anchor="w",
                bg=BG2, fg=FG,
                activebackground=BG3, activeforeground=ACCENT,
                relief="flat", bd=0, cursor="hand2",
                font=("Helvetica", 11),
                padx=8, pady=14,
                command=make_enter(name)
            )
            row_btn.pack(side="left", fill="x", expand=True)

            tk.Label(row, text=f"{count} peer(s)  ›",
                     bg=BG2, fg=FG2, font=("Courier", 9)).pack(side="right", padx=16)

    def _refresh_lobby(self):
        try:
            resp = sig_send(self.server_ip, self.server_port, "LIST")
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        self._populate_rooms(self._lobby_inner, resp)

    def _create_room_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Nova sala")
        dlg.configure(bg=BG)
        dlg.geometry("340x240")
        dlg.resizable(False, False)
        dlg.grab_set()

        pad = frame(dlg)
        pad.pack(padx=24, pady=24, fill="both")

        tk.Label(pad, text="Nova sala", bg=BG, fg=ACCENT,
                 font=FONT_BIG).pack(anchor="w", pady=(0, 16))

        tk.Label(pad, text="Nome da sala", bg=BG, fg=FG2,
                 font=("Helvetica", 9)).pack(anchor="w")
        rname = styled_entry(pad)
        rname.pack(fill="x", pady=(2, 10), ipady=6)

        tk.Label(pad, text="Senha", bg=BG, fg=FG2,
                 font=("Helvetica", 9)).pack(anchor="w")
        rpwd = styled_entry(pad, show="●")
        rpwd.pack(fill="x", pady=(2, 16), ipady=6)

        err_lbl = tk.Label(pad, text="", bg=BG, fg=DANGER, font=("Helvetica", 9))
        err_lbl.pack()

        def create():
            n = rname.get().strip()
            p = rpwd.get().strip()
            if not n or not p:
                err_lbl.config(text="Preencha tudo.")
                return
            port = self._find_free_port()
            msg  = f"CREATE|{n}|{p}|{self.my_name}|{port}"
            try:
                resp = sig_send(self.server_ip, self.server_port, msg)
            except Exception as e:
                err_lbl.config(text=str(e))
                return
            if resp.startswith("ERR"):
                err_lbl.config(text=resp)
                return
            dlg.destroy()
            self._enter_room(n, p, port, resp)

        styled_button(pad, "Criar ›", create).pack(fill="x")
        rname.focus()
        rname.bind("<Return>", lambda e: rpwd.focus())
        rpwd.bind("<Return>", lambda e: create())

    def _join_room_dialog(self, room_name):
        dlg = tk.Toplevel(self)
        dlg.title(f"Entrar — {room_name}")
        dlg.configure(bg=BG)
        dlg.geometry("320x190")
        dlg.resizable(False, False)
        dlg.grab_set()

        pad = frame(dlg)
        pad.pack(padx=24, pady=24, fill="both")

        tk.Label(pad, text=f"Entrar em «{room_name}»", bg=BG, fg=FG,
                 font=FONT_MED).pack(anchor="w", pady=(0, 12))

        tk.Label(pad, text="Senha", bg=BG, fg=FG2,
                 font=("Helvetica", 9)).pack(anchor="w")
        pwd_e = styled_entry(pad, show="●")
        pwd_e.pack(fill="x", pady=(2, 12), ipady=6)

        err_lbl = tk.Label(pad, text="", bg=BG, fg=DANGER, font=("Helvetica", 9))
        err_lbl.pack()

        def join():
            p = pwd_e.get().strip()
            if not p:
                err_lbl.config(text="Digite a senha.")
                return
            port = self._find_free_port()
            msg  = f"JOIN|{room_name}|{p}|{self.my_name}|{port}"
            try:
                resp = sig_send(self.server_ip, self.server_port, msg)
            except Exception as e:
                err_lbl.config(text=str(e))
                return
            if resp.startswith("ERR"):
                err_lbl.config(text=resp)
                return
            dlg.destroy()
            self._enter_room(room_name, p, port, resp)

        styled_button(pad, "Entrar ›", join).pack(fill="x")
        pwd_e.focus()
        pwd_e.bind("<Return>", lambda e: join())

    def _find_free_port(self):
        port = PEER_PORT
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("0.0.0.0", port))
                    return port
                except OSError:
                    port += 1

    def _enter_room(self, room_name, password, my_port, server_resp):
        self.room_name    = room_name
        self.room_password= password
        self.my_port      = my_port
        self.fernet       = Fernet(derive_key(password))

        # parse peers existentes: "OK|nome|ip|porta;nome|ip|porta"
        self.peers = {}
        if server_resp.startswith("OK|"):
            payload = server_resp[3:]
            if payload:
                for entry in payload.split(";"):
                    parts = entry.split("|")
                    if len(parts) == 3:
                        self.peers[parts[0]] = {
                            "ip": parts[1],
                            "tcp_port": int(parts[2])
                        }

        # inicia listener
        if self.listener:
            self.listener.stop()
        self.listener = PeerListener(my_port, self.fernet, self._on_peer_message)
        self.listener.start()

        # inicia polling de peers
        self._poll_active = True
        threading.Thread(target=self._poll_peers_loop, daemon=True).start()

        self.show_chat()

    def _poll_peers_loop(self):
        """Reinscreve na sala a cada 5s para descobrir novos peers."""
        while self._poll_active:
            time.sleep(5)
            if not self._poll_active:
                break
            try:
                msg  = f"JOIN|{self.room_name}|{self.room_password}|{self.my_name}|{self.my_port}"
                resp = sig_send(self.server_ip, self.server_port, msg)
                if resp.startswith("OK|"):
                    new_peers = {}
                    payload = resp[3:]
                    if payload:
                        for entry in payload.split(";"):
                            parts = entry.split("|")
                            if len(parts) == 3:
                                new_peers[parts[0]] = {
                                    "ip": parts[1],
                                    "tcp_port": int(parts[2])
                                }
                    # detecta entradas e saídas
                    joined = set(new_peers) - set(self.peers)
                    left   = set(self.peers) - set(new_peers)
                    self.peers = new_peers
                    if joined or left:
                        def update(j=joined, l=left):
                            for name in j:
                                self._system_msg(f"{name} entrou na sala.")
                            for name in l:
                                self._system_msg(f"{name} saiu da sala.")
                            self._refresh_peers_sidebar()
                        self.after(0, update)
            except Exception as e:
                print(f"[poll] erro: {e}")

    # Tela 3: chat

    def show_chat(self):
        self.geometry("860x560")
        self._center()
        self.resizable(True, True)
        f = frame(self)

        # cabeçalho
        hdr = frame(f, bg=BG2)
        hdr.pack(fill="x")
        hdr.configure(highlightthickness=1, highlightbackground=BORDER)

        hdr_l = frame(hdr, bg=BG2)
        hdr_l.pack(side="left", padx=16, pady=10)
        tk.Label(hdr_l, text="◈", bg=BG2, fg=ACCENT,
                 font=("Courier", 14, "bold")).pack(side="left")
        tk.Label(hdr_l, text=f"  {self.room_name}", bg=BG2, fg=FG,
                 font=("Helvetica", 12, "bold")).pack(side="left")
        tk.Label(hdr_l, text=f"  —  {self.my_name}", bg=BG2, fg=FG2,
                 font=("Courier", 9)).pack(side="left")

        def leave():
            self._poll_active = False
            if self.listener:
                self.listener.stop()
            try:
                sig_send(self.server_ip, self.server_port,
                         f"LEAVE|{self.room_name}|{self.my_name}")
            except: pass
            self.peers    = {}
            self.fernet   = None
            self.listener = None
            self.resizable(False, False)
            self.geometry("520x420")
            self._center()
            self.show_connect()

        styled_button(hdr, "Sair", leave, color=DANGER).pack(side="right", padx=16, pady=8)

        # body
        body = frame(f)
        body.pack(fill="both", expand=True)

        # sidebar peers
        sidebar = frame(body, bg=BG2, width=160)
        sidebar.pack(side="right", fill="y")
        sidebar.pack_propagate(False)
        sidebar.configure(highlightthickness=1, highlightbackground=BORDER)

        tk.Label(sidebar, text="PEERS", bg=BG2, fg=FG2,
                 font=("Courier", 8)).pack(pady=(12, 6))

        self._peers_frame = frame(sidebar, bg=BG2)
        self._peers_frame.pack(fill="x", padx=8)

        # área de mensagens
        chat_area = frame(body, bg=BG)
        chat_area.pack(side="left", fill="both", expand=True)

        self._chat_text = tk.Text(
            chat_area,
            bg=BG, fg=FG,
            font=FONT_MONO,
            relief="flat", bd=0,
            state="disabled",
            wrap="word",
            padx=16, pady=12,
            spacing2=4,
            highlightthickness=0,
            selectbackground=BG3,
        )
        self._chat_text.pack(fill="both", expand=True)

        # tags de cor
        self._chat_text.tag_config("time",  foreground=FG2)
        self._chat_text.tag_config("name",  foreground=ACCENT)
        self._chat_text.tag_config("me",    foreground=SUCCESS)
        self._chat_text.tag_config("sys",   foreground=FG2, font=("Courier", 9))
        self._chat_text.tag_config("msg",   foreground=FG)

        # barra de entrada
        input_bar = frame(f, bg=BG2)
        input_bar.pack(fill="x")
        input_bar.configure(highlightthickness=1, highlightbackground=BORDER)

        self._msg_var = tk.StringVar()
        msg_e = styled_entry(input_bar, textvariable=self._msg_var)
        msg_e.pack(side="left", fill="x", expand=True,
                   padx=(16, 8), pady=12, ipady=7)

        def send():
            text = self._msg_var.get().strip()
            if not text:
                return
            self._msg_var.set("")
            full = f"{self.my_name}: {text}"
            self._append_msg(self.my_name, text, own=True)
            threading.Thread(
                target=broadcast,
                args=(self.peers, self.fernet, full, self.my_name),
                daemon=True
            ).start()

        styled_button(input_bar, "Enviar", send).pack(side="right", padx=(0, 16), pady=12)
        msg_e.bind("<Return>", lambda e: send())
        msg_e.focus()

        self._switch(f)
        self._refresh_peers_sidebar()
        self._system_msg(f"Você entrou na sala «{self.room_name}». Mensagens são criptografadas.")

    def _refresh_peers_sidebar(self):
        for w in self._peers_frame.winfo_children():
            w.destroy()

        row = frame(self._peers_frame, bg=BG2)
        row.pack(fill="x", pady=2)
        dot = tk.Label(row, text="●", bg=BG2, fg=SUCCESS, font=("Courier", 9))
        dot.pack(side="left")
        tk.Label(row, text=f" {self.my_name} (eu)", bg=BG2, fg=FG,
                 font=("Helvetica", 9)).pack(side="left")

        for name in self.peers:
            row = frame(self._peers_frame, bg=BG2)
            row.pack(fill="x", pady=2)
            tk.Label(row, text="●", bg=BG2, fg=ACCENT, font=("Courier", 9)).pack(side="left")
            tk.Label(row, text=f" {name}", bg=BG2, fg=FG,
                     font=("Helvetica", 9)).pack(side="left")

    def _append_msg(self, sender: str, text: str, own=False):
        t = time.strftime("%H:%M")
        self._chat_text.config(state="normal")
        self._chat_text.insert("end", f"[{t}] ", "time")
        self._chat_text.insert("end", f"{sender}", "me" if own else "name")
        self._chat_text.insert("end", f":  {text}\n", "msg")
        self._chat_text.config(state="disabled")
        self._chat_text.see("end")

    def _system_msg(self, text: str):
        self._chat_text.config(state="normal")
        self._chat_text.insert("end", f"  ·  {text}\n", "sys")
        self._chat_text.config(state="disabled")
        self._chat_text.see("end")

    def _on_peer_message(self, text: str):
        # formato esperado: "nome: mensagem"
        if ": " in text:
            sender, msg = text.split(": ", 1)
        else:
            sender, msg = "?", text
        self.after(0, lambda: self._append_msg(sender, msg, own=False))


# Main
if __name__ == "__main__":
    app = App()
    app.mainloop()