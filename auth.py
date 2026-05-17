"""
模块描述：账号认证与 JWT 会话模块，负责密码哈希、登录锁定、账号文件和管理员初始化。
"""

import os
import json
import time
import hmac
import hashlib
import base64
import threading
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback for local development.
    fcntl = None


load_dotenv(".env")

MIN_SECRET_LENGTH = 32
PASSWORD_MIN_LENGTH = 6
LOCKOUT_FAIL_LIMIT = 3
LOCKOUT_SECONDS = 2 * 3600
LOCKOUT_WINDOW_SECONDS = 15 * 60
INSECURE_DEFAULT_ADMIN_HASH = (
    "cf632ecdd2c9b4e67cd76de4db6b785d$"
    "12b8bd1ec5414d7a46abf6b92a4bc0319ca7b9662bba71bc9776dcbefc4c0177"
)


def _get_required_secret_key() -> str:
    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set before starting GDUT-Lawyer.")
    if len(secret_key) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters long.")
    return secret_key


SECRET_KEY = _get_required_secret_key()

DATA_DIR = os.environ.get("LAWYANCE_DATA_DIR") or os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)
ACCOUNT_FILE = os.path.join(DATA_DIR, "account.json")
LOCKOUT_FILE = os.path.join(DATA_DIR, "lockout.json")
AUTH_STATE_LOCK_FILE = os.path.join(DATA_DIR, ".auth_state.lock")
_AUTH_STATE_LOCK = threading.RLock()
_AUTH_STATE_LOCK_DEPTH = threading.local()


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    ).hex()
    return f"{salt}${actual_hash}"


@contextmanager
def _auth_state_lock():
    os.makedirs(DATA_DIR, exist_ok=True)
    with _AUTH_STATE_LOCK:
        depth = getattr(_AUTH_STATE_LOCK_DEPTH, "value", 0)
        if depth:
            _AUTH_STATE_LOCK_DEPTH.value = depth + 1
            try:
                yield
            finally:
                _AUTH_STATE_LOCK_DEPTH.value = depth
            return

        with open(AUTH_STATE_LOCK_FILE, "a", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            _AUTH_STATE_LOCK_DEPTH.value = 1
            try:
                yield
            finally:
                _AUTH_STATE_LOCK_DEPTH.value = 0
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_json(path: str, payload: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _ensure_account_file():
    with _auth_state_lock():
        if os.path.exists(ACCOUNT_FILE):
            try:
                with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                    accounts = json.load(f)
                admin_hash = accounts.get("admin", {}).get("hash") if isinstance(accounts.get("admin"), dict) else accounts.get("admin")
                if admin_hash == INSECURE_DEFAULT_ADMIN_HASH:
                    raise RuntimeError(
                        "Insecure default admin account detected. Replace data/account.json or bootstrap a new admin password."
                    )
            except RuntimeError:
                raise
            except Exception:
                pass
            return

        initial_password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
        if not initial_password:
            raise RuntimeError(
                "No account file exists. Set INITIAL_ADMIN_PASSWORD once to bootstrap the admin account."
            )
        if len(initial_password) < PASSWORD_MIN_LENGTH:
            raise RuntimeError(f"INITIAL_ADMIN_PASSWORD must be at least {PASSWORD_MIN_LENGTH} characters long.")
        if initial_password == "password":
            raise RuntimeError("INITIAL_ADMIN_PASSWORD cannot use the old insecure default password.")

        _write_json(
            ACCOUNT_FILE,
            {
                "admin": {
                    "hash": hash_password(initial_password),
                    "role": "admin",
                }
            },
        )


_ensure_account_file()


def get_accounts_data():
    with _auth_state_lock():
        try:
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                accounts = json.load(f)
        except Exception:
            return {}

        dirty = False
        for k, v in accounts.items():
            if isinstance(v, str):
                role = "admin" if k == "admin" else "user"
                accounts[k] = {"hash": v, "role": role}
                dirty = True

        if dirty:
            _write_json(ACCOUNT_FILE, accounts)

        return accounts


def get_user_role(username: str) -> str:
    accounts = get_accounts_data()
    user_data = accounts.get(username)
    if user_data:
        return user_data.get("role", "user")
    return "user"


def list_accounts() -> list:
    accounts = get_accounts_data()
    return [{"username": k, "role": v.get("role", "user")} for k, v in accounts.items()]


def add_or_update_account(username: str, password: str, role: str = "user") -> tuple[bool, str]:
    normalized_role = role if role in {"admin", "user"} else "user"

    if len(password) < PASSWORD_MIN_LENGTH:
        return False, "密码长度不能小于6位"

    with _auth_state_lock():
        accounts = get_accounts_data()

        if username in accounts and accounts[username].get("role") == "admin" and normalized_role != "admin":
            return False, "不能将管理员账号降级为普通用户"

        accounts[username] = {"hash": hash_password(password), "role": normalized_role}

        try:
            _write_json(ACCOUNT_FILE, accounts)
            return True, "操作成功"
        except Exception as e:
            return False, f"保存失败: {str(e)}"


def delete_account(username: str) -> tuple[bool, str]:
    if username == "admin":
        return False, "不能删除系统管理员账号"

    with _auth_state_lock():
        accounts = get_accounts_data()
        if username not in accounts:
            return False, "账号不存在"

        try:
            del accounts[username]
            _write_json(ACCOUNT_FILE, accounts)
            return True, "账号已删除"
        except Exception as e:
            return False, f"删除失败: {str(e)}"


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        salt, expected_hash = hashed_password.split("$")
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100000,
        ).hex()
        return hmac.compare_digest(actual_hash, expected_hash)
    except (AttributeError, ValueError):
        return False


def create_token(username: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode("utf-8").rstrip("=")
    payload_dict = {"sub": username, "exp": int(time.time()) + 7 * 24 * 3600}
    payload = base64.urlsafe_b64encode(json.dumps(payload_dict).encode("utf-8")).decode("utf-8").rstrip("=")
    signature = base64.urlsafe_b64encode(
        hmac.new(SECRET_KEY.encode("utf-8"), f"{header}.{payload}".encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8").rstrip("=")
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> Optional[str]:
    if not token:
        return None
    try:
        header, payload, signature = token.split(".")
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(SECRET_KEY.encode("utf-8"), f"{header}.{payload}".encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8").rstrip("=")
        if not hmac.compare_digest(signature, expected_signature):
            return None
        payload += "=" * (-len(payload) % 4)
        payload_dict = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
        if payload_dict["exp"] < time.time():
            return None
        return payload_dict["sub"]
    except Exception:
        return None


def _read_lockouts() -> dict:
    with _auth_state_lock():
        if not os.path.exists(LOCKOUT_FILE):
            return {}
        try:
            with open(LOCKOUT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _write_lockouts(lockouts: dict):
    with _auth_state_lock():
        _write_json(LOCKOUT_FILE, lockouts)


def check_lockout(username: str) -> Optional[str]:
    with _auth_state_lock():
        record = _read_lockouts().get(username)
    if not record:
        return None

    now = time.time()
    if record.get("locked_until", 0) > now:
        remain = int((record["locked_until"] - now) / 60) + 1
        return f"账户已被锁定，请 {remain} 分钟后再试。"
    return None


def record_login_attempt(username: str, success: bool):
    try:
        with _auth_state_lock():
            now = time.time()
            lockouts = _read_lockouts()

            if success:
                lockouts.pop(username, None)
            else:
                record = lockouts.get(username, {"fails": 0, "locked_until": 0, "first_failed_at": now})
                if record.get("locked_until", 0) <= now:
                    first_failed_at = record.get("first_failed_at", now)
                    if record.get("locked_until", 0) > 0 or now - first_failed_at > LOCKOUT_WINDOW_SECONDS:
                        record = {"fails": 0, "locked_until": 0, "first_failed_at": now}
                    record["fails"] = int(record.get("fails", 0)) + 1
                    if record["fails"] >= LOCKOUT_FAIL_LIMIT:
                        record["locked_until"] = int(now + LOCKOUT_SECONDS)
                    lockouts[username] = record

            _write_lockouts(lockouts)
    except Exception as e:
        print(f"Error recording login attempt: {e}")


def authenticate_user(username, password):
    lock_msg = check_lockout(username)
    if lock_msg:
        return False, lock_msg

    accounts = get_accounts_data()
    if not accounts:
        return False, "账号系统配置错误，请联系管理员"

    user_data = accounts.get(username)
    if not user_data:
        record_login_attempt(username, False)
        return False, "用户名或密码错误"

    hashed = user_data.get("hash")
    if verify_password(password, hashed):
        record_login_attempt(username, True)
        return True, "登录成功"

    record_login_attempt(username, False)
    return False, "用户名或密码错误"
