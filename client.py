import socket
import threading
import sys

HOST = "127.0.0.1"
PORT = 9000

def receive_loop(sock: socket.socket):
    """Thread que fica ouvindo mensagens do servidor."""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                print("\n[Conexão encerrada pelo servidor]")
                break
            # Imprime sem quebrar a linha que o usuário está digitando
            print(f"\r{data.decode('utf-8').rstrip()}")
            print("> ", end="", flush=True)
    except (ConnectionResetError, OSError):
        print("\n[Conexão perdida]")
    finally:
        sock.close()
        # Força saída do input() na thread principal
        import os, signal
        try:
            os.kill(os.getpid(), signal.SIGINT)
        except Exception:
            pass

def send_loop(sock: socket.socket):
    """Thread (main) que lê stdin e envia ao servidor."""
    try:
        while True:
            print("> ", end="", flush=True)
            msg = input()
            if msg.lower() in ("/sair", "/quit", "/exit"):
                print("Saindo...")
                break
            if msg:
                sock.sendall((msg + "\n").encode("utf-8"))
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        sock.close()

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    print(f"Conectando em {host}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
    except ConnectionRefusedError:
        print("Erro: não foi possível conectar. O servidor está rodando?")
        sys.exit(1)

    print("Conectado!\n")

    # Thread de recepção (daemon: morre quando o processo principal sair)
    t = threading.Thread(target=receive_loop, args=(sock,), daemon=True)
    t.start()

    # Loop de envio na thread principal
    send_loop(sock)

if __name__ == "__main__":
    main()