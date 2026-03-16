from socket import *
import threading

peers = {}
lock = threading.Lock()

def handle(conn, addr):
    data = conn.recv(1024).decode().strip()
    name, port = data.split(":")

    #!!
    with lock:
        peers[name] = {"ip": addr[0], "port": port}
        resposta = ";".join(f"{n}:{info['ip']}:{info['port']}" for n, info in peers.items())
        
    conn.sendall(resposta.encode())
    conn.close()

server = socket(AF_INET, SOCK_STREAM)
server.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1) #!!
server.bind(("0.0.0.0", 9005))
server.listen()
print("Servidor escutando na porta 9005...")

while True:
    conn, addr = server.accept()
    threading.Thread(target=handle, args=(conn, addr)).start()
