from socket import *
import threading

# Estrutura do dict rooms
# rooms[room_name] = {
#   "password": str,
#   "peers": { name: {"ip": str, "tcp_port": int} }
# }
rooms = {}
lock  = threading.Lock()

PORT = 9005

# Explicações das Requisições:
#
# client → server:
#   "LIST"
#   "CREATE|sala|senha|nome|porta_peer"
#   "JOIN|sala|senha|nome|porta_peer"
#   "LEAVE|sala|nome"
#
# server → client:
#   "ROOMS|sala|qtd;sala|qtd"
#   "OK|nome|ip|porta;nome|ip|porta"
#   "ERR|motivo"

# Transforma o IP em formato numérico padrão (remove os ".")
def normalize_ip(ip):
    return ip.split("%")[0].strip("[]")

# Gerencia a conexão
def handle(conn, addr):
    try:
        data = conn.recv(4096).decode().strip()         # Recebe a solicitação do cliente, que pode ser "LIST |...", "CREATE |...", "JOIN |..." ou "LEAVE |..."
        parts = data.split("|")                         # Remove o "|"
        client_ip = normalize_ip(addr[0])               # Normaliza o IP do cliente.

        if data == "LIST":                              # Caso a requisição do cliente seja listar as salas:
            with lock:                                  # Garante acesso exclusivo, para evitar race conditions
                payload = ";".join(                     # Percorre todas as salas, conta a quantidade de peers e junta tudo em uma string.
                    f"{name}|{len(info['peers'])}"
                    for name, info in rooms.items()
                )
            conn.sendall(f"ROOMS|{payload}".encode())   # Envia a lista com salas/peers para o cliente
            return

        if parts[0] == "LEAVE" and len(parts) == 3:     # Caso o usuário tenha escolhido sair da sala:
            _, room_name, name = parts                  
            with lock:                                  # Acesso exclusivo, evita race conditions
                if room_name in rooms:                  # Verifica se a sala existe
                    rooms[room_name]["peers"].pop(name, None) # Remove o usuário da list de peers da sala
                    if not rooms[room_name]["peers"]:   # Se a sala estiver vazia, deleta ela.
                        del rooms[room_name]
            conn.sendall(b"OK|")                        # Envia um sinal "OK", informando ao cliente que o usuário foi removido
            return

        if len(parts) != 5:                             # Tratamento para requisição do cliente inválida.
            conn.sendall(b"ERR|formato_invalido")
            return

        # Requisição, nome da sala, senha da sala, nome do cliente, porta do cliente
        action, room_name, password, name, port_str = parts 

        with lock:                                      # Garante acesso exclusivo
            if action == "CREATE":                      # Cliente solicita a criação de uma sala:
                if room_name in rooms:                  # Tratamento para sala já existente        
                    conn.sendall(b"ERR|sala_ja_existe")
                    return
                rooms[room_name] = {"password": password, "peers": {}} # Adiciona a sala na lista de salas

            if action in ("CREATE", "JOIN"):            # Entra em uma sala, tanto para o usuário que selecionou a sala quanto para o que acabou de criar.
                if room_name not in rooms:              # Verificação de sala inexistente
                    conn.sendall(b"ERR|sala_nao_existe")
                    return
                if rooms[room_name]["password"] != password: # Veficicação de senha
                    conn.sendall(b"ERR|senha_incorreta")
                    return

                rooms[room_name]["peers"][name] = {     # Atrbui o IP e Porta do usuário ao peer da sala. 
                    "ip":       client_ip,
                    "tcp_port": int(port_str),
                }

                peers = rooms[room_name]["peers"]       # Obtém a lista de todos os peers da sala (menos o próprio usuário)
                others = ";".join(
                    f"{n}|{info['ip']}|{info['tcp_port']}"
                    for n, info in peers.items()
                    if n != name
                )
                conn.sendall(f"OK|{others}".encode())   # Envia um sinal "OK" para o cliente, junto com a lista de todos os PEERS daquela sala
            else:
                conn.sendall(b"ERR|acao_desconhecida")

    except Exception as e:
        print(f"[server] erro: {e}")
    finally:
        conn.close()

# Inicialização tenta conectar IPV6, se n der certo vai IPV4

try:
    srv = socket(AF_INET6, SOCK_STREAM)                             # Instancia um socket TCP (SOCK_STREAM) com endereçamento IPV6 (AF_INET6)
    srv.setsockopt(IPPROTO_IPV6, IPV6_V6ONLY, 0)                    # Define a conexão para somente IPV6
    srv.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)                     # Avisa ao sistema operacional para reutilizar a porta, caso ela esteja no estado WAIT                  
    srv.bind(("", PORT))                                            # Atribui o servidor à porta 9005 
    print(f"[server] dual-stack (IPv4+IPv6) na porta {PORT}")
except OSError:                                                     # Em caso de erro, testa a criação do socket com IPV4
    srv = socket(AF_INET, SOCK_STREAM)                              # Instancia um socket TCP (SOCK_STREAM) com endereçamento IPV4 (AF_INET)
    srv.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)                     # Avisa ao sistema operacional para reutilizar a porta, caso ela esteja no estado WAIT
    srv.bind(("0.0.0.0", PORT))                                     # Atribui a variável "PORT" (9005) como porta da conexão
    print(f"[server] IPv4 na porta {PORT}")                 

srv.listen()                                                        # Escuta requisições no endereço local e na porta "PORT" (9005)

while True:
    conn, addr = srv.accept()                                       # Aceita a conexão (conn = objeto socket; addr = {host, porta, flowinfo, scope_id})
    #Cria uma thread para receber conexões e enviar para handle
    #handle = função que será executda concorrentemente
    #"args = (conn, addr)" = argumentos da função handle
    #"daemon = trua" = Garante que ao fechar o programa todas as threads de atendimento sejam encerradas também. 
    threading.Thread(target=handle, args=(conn, addr), daemon=True).start() 