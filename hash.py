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
    print("\n账号现由 SQLite（data/auth.sqlite3）管理，请通过后台「系统管理 → 全部账号」")
    print("为账号重置密码，不要把摘要直接写入文件。若确需手工写入数据库，请保持同样的")
    print("pbkdf2_sha256 格式，并同步刷新该账号的 auth_version 以作废旧令牌。")
