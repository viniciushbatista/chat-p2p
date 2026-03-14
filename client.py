import socket

host = input("IP do servidor: ")
port = int(input("Porta: "))

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((host, port))

msg = client.recv(1024)
print(msg.decode())

password = input("Senha: ")
client.sendall(password.encode())

response = client.recv(1024)
print(response.decode())

client.close()