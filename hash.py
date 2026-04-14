import getpass
import hashlib
import os
import json

def hash_password(password: str) -> str:
    # Use a fixed salt for simplicity or generate a random one and prepend it.
    # Let's use a random salt and prepend it. format: salt$hash
    salt = os.urandom(16).hex()
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return f"{salt}${hashed}"

def verify_password(password: str, hashed_password: str) -> bool:
    try:
        salt, expected_hash = hashed_password.split('$')
        actual_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
        return actual_hash == expected_hash
    except ValueError:
        return False

if __name__ == "__main__":
    print("=== GDUT-Lawyer 密码哈希生成工具 ===")
    password = getpass.getpass("请输入账号明文密码: ")
    confirm_password = getpass.getpass("请再次输入确认: ")
    
    if password != confirm_password:
        print("两次输入的密码不一致！")
        exit(1)
        
    hashed = hash_password(password)
    print("\n生成的密码哈希值为:")
    print("-" * 50)
    print(hashed)
    print("-" * 50)
    print("\n请将此哈希值保存到 /data/account.json 对应的密码字段中。例如：")
    print('{\n    "admin": "' + hashed + '"\n}')
