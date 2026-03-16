import socket
import threading
import sys
import time

HOST = "0.0.0.0"
PORT = 9000

clients = []       # lista de (socket, nome)
lock = threading.Lock()

def broadcast(message: str, sender_socket: socket.socket):
    """Envia mensagem para o outro cliente (não para o remetente)."""
    with lock:
        for sock, name in clients:
            if sock is not sender_socket:
                try:
                    sock.sendall((message + "\n").encode("utf-8"))
                except Exception:
                    pass

def handle_client(conn: socket.socket, addr):
    """Thread dedicada a uma conexão."""
    print(f"[+] Conexão de {addr}")

    # Pede o apelido do usuário
    try:
        conn.sendall(b"Digite seu nome: ")
        name = conn.recv(1024).decode("utf-8").strip() or f"User@{addr[0]}"
    except Exception:
        conn.close()
        return

    with lock:
        clients.append((conn, name))

    print(f"[+] {name} entrou no chat.")
    broadcast(f"*** {name} entrou no chat ***", conn)
    conn.sendall(f"Bem-vindo, {name}! Aguardando o outro usuário...\n".encode("utf-8"))

    # Espera o segundo usuário
    while True:
        with lock:
            count = len(clients)
        if count == 2:
            break
        time.sleep(0.2)

    conn.sendall(b"Sala completa! Pode comecar a conversar.\n")

    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            msg = data.decode("utf-8").strip()
            if not msg:
                continue
            formatted = f"[{name}] {msg}"
            print(formatted)
            broadcast(formatted, conn)
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        print(f"[-] {name} saiu.")
        broadcast(f"*** {name} saiu do chat ***", conn)
        with lock:
            clients[:] = [(s, n) for s, n in clients if s is not conn]
        conn.close()

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(2)
    print(f"Servidor escutando em {host}:{port} — aguardando 2 usuários...")

    try:
        while True:
            with lock:
                count = len(clients)
            if count >= 2:
                # Sala cheia; rejeita novas conexões temporariamente
                time.sleep(0.5)
                continue
            server.settimeout(1.0)
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.close()

if __name__ == "__main__":
    main()
