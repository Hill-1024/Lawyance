"""
模块描述：命令行密码哈希生成工具，为账号文件生成与 auth.py 完全一致的 PBKDF2 摘要。
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.password_hashing import hash_password, verify_password  # noqa: E402


if __name__ == "__main__":
    print("=== Lawver 密码哈希生成工具 ===")
    password = getpass.getpass("请输入账号明文密码: ")
    confirm_password = getpass.getpass("请再次输入确认: ")

    if password != confirm_password:
        print("两次输入的密码不一致！")
        exit(1)

    hashed = hash_password(password)
    assert verify_password(password, hashed), "哈希自检失败"
    print("\n生成的密码哈希值为:")
    print("-" * 50)
    print(hashed)
    print("-" * 50)
    print("\n请将此哈希值保存到 /data/account.json 对应的密码字段中。例如：")
    print('{\n    "admin": "' + hashed + '"\n}')
