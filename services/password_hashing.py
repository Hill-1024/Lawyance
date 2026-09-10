"""
模块描述：PBKDF2 密码摘要的单一实现，供 auth.py 与服务启动/CLI 工具复用。
"""

import hashlib
import hmac
import os


PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 100_000


def _pbkdf2_hex(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()


def hash_password(password: str) -> str:
    """生成 `pbkdf2_sha256$<iterations>$<salt>$<digest>` 格式摘要。"""
    salt = os.urandom(16).hex()
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt}${_pbkdf2_hex(password, salt, PBKDF2_ITERATIONS)}"


def _parse_password_record(hashed_password: str) -> tuple[int, str, str] | None:
    """返回 (iterations, salt, digest)，兼容历史 `salt$digest` 格式。"""
    if not isinstance(hashed_password, str):
        return None
    parts = hashed_password.split("$")
    if len(parts) == 4 and parts[0] == PBKDF2_ALGORITHM:
        try:
            iterations = int(parts[1])
        except ValueError:
            return None
        if iterations <= 0:
            return None
        return iterations, parts[2], parts[3]
    if len(parts) == 2:
        return LEGACY_PBKDF2_ITERATIONS, parts[0], parts[1]
    return None


def verify_password(password: str, hashed_password: str) -> bool:
    record = _parse_password_record(hashed_password)
    if record is None:
        return False
    iterations, salt, expected_hash = record
    try:
        actual_hash = _pbkdf2_hex(password, salt, iterations)
    except (AttributeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual_hash, expected_hash)


def password_needs_rehash(hashed_password: str) -> bool:
    """旧格式或迭代数不足的摘要需要在下次登录成功后就地升级。"""
    record = _parse_password_record(hashed_password)
    if record is None:
        return False
    iterations, _, _ = record
    return iterations < PBKDF2_ITERATIONS
