from socket import *
connection_status = 0 # 0 = servidor encerrado ou não existente; 1 = servidor ativo e escutando

HOST = "0.0.0.0" # Host local, utilizado para testes durante essa etapa inicial
port = int(input("Porta do servidor: "))

while(int(port) < 50000 or int(port) > 99999): # Utiliza portas somente no intervalo entre 5000 e 8000, para evitar conflito com portas conhecidas
    port = int(input("Número da porta deve estar no intervalo [5000,8000]"))

password = input("Senha para conexão: ")

server = socket(AF_INET, SOCK_STREAM)   # Cria o socket tcp
server.bind((HOST, port))               # Atribui a porta "0.0.0.0" ao servidor
server.listen(1)                        # Servidor aguardando conexão...

print(f"Servidor ouvindo em 0.0.0.0:{port}")

conn, addr = server.accept()            # Conexão e endereço recebidos pelo servidor
print(f"Conexão recebida de {addr}")

conn.sendall(b"Digite a senha: ")       # Servidor solicita senha à conexão
client_password = conn.recv(1024).decode().strip()  # Servidor recebe a senha

if(client_password == password):
    connection_status = 1   
    conn.sendall(b"Acesso permitido")
    print("Cliente autenticado")

    while True:
        data = conn.recv(1024)
        if not data:
            break

        print("Cliente: ", data.decode())
        conn.sendall(b"Mensagem Recebida\n")
else:
    conn.sendall(b"Senha incorreta\n")
    print("Senha recebida incorreta, conexão encerrada\n")
    connection_status = 0
    conn.close()
    server.close()

if(connection_status == 1):
    conn.close()
    server.close()
