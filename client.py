from socket import *
import threading
import sys
import time

SIGNAL_SERVER_HOST = "0.0.0.0"
SIGNAL_SERVER_PORT = 9005

# Registra no servidor de inicialização e retorna a lista de peers
def register(name, port):
    s = socket(AF_INET, SOCK_STREAM)
    s.connect((SIGNAL_SERVER_HOST, SIGNAL_SERVER_PORT))
    s.sendall(f"{name}:{port}".encode())

    peers_raw = s.recv(4096).decode()
    s.close()

    peers = {}
    for entry in peers_raw.split(";"):
        if entry:
            n, ip, p = entry.split(":")
            peers[n] = {"ip":ip, "port": p}

    return peers

def start_server(port, name):
    s =  socket(AF_INET, SOCK_STREAM)
    s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen()

    while True:
        conn, addr = s.accept()
        threading.Thread(target=receive, args=(conn, addr)).start()

def receive(conn, addr):
    while True:
        try:
            msg = conn.recv(1024).decode()
            if not msg:
                break
            print(f"\n[mensagem recebida] {msg}\nVocê: ", end="", flush=True)
        except:
            break
    conn.close()

def connect_peer(ip, port):
    for i in range(100):
        try:
            s = socket(AF_INET, SOCK_STREAM)
            s.connect((ip, port))
            return s
        except ConnectionRefusedError:
            print(f"Tentativa {i}")
            time.sleep(1)
    raise ConnectionRefusedError(f"Não foi possível conectar a {ip}:{port} após {i} tentativas")

def send(conn, name):
    while True:
        msg = input("Você: ")
        try:
            conn.send(f"{name}: {msg}".encode())
        except:
            print("Conexão perdida")
            break

def main():
    name = sys.argv[1]
    port = int(sys.argv[2])

    threading.Thread(target=start_server, args=(port, name), daemon=True).start()
    print(f"[{name}] escutando na porta {port}")

    peers = register(name, port)
    print(f"peers conhecidos: {peers}")

    connections = {}
    for peer_name, info in peers.items():
        if peer_name != name:
            try:
                conn = connect_peer(info["ip"], int(info["port"])) 
                connections[peer_name] = conn
                print(f"Conectado diretamente a {peer_name}")
            except Exception as e:
                print(f"Não foi possível conectar a {peer_name}: {e}")

    if connections:
        target_peer = list(connections.values())[0]
        send(target_peer, name)
    else:
        print("Aguardando outros peers se conectarem...")
        threading.Event().wait()

main()