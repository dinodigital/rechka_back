from cryptography.fernet import Fernet


# Функция для генерации ключа
def generate_key():
    return Fernet.generate_key()


# Функция для шифрования сообщения
def encrypt(message: str, key: str) -> str:
    fernet = Fernet(key.encode())
    encrypted_message = fernet.encrypt(message.encode()).decode()
    return encrypted_message


# Функция для расшифровки сообщения
def decrypt(encrypted_message: str, key: str) -> str:
    fernet = Fernet(key.encode())
    decrypted_message = fernet.decrypt(encrypted_message.encode()).decode()
    return decrypted_message

