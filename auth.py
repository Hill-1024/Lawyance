"""
模块描述：账号认证与 JWT 会话模块，负责密码哈希、登录锁定、账号文件和管理员初始化。
"""

import os
import json
import time
import hmac
import hashlib
import base64
import logging
import re
import threading
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv

from services.password_hashing import (
    PBKDF2_ITERATIONS,
    hash_password,
    password_needs_rehash,
    verify_password,
)

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
# The aggregate account bucket starts later and applies short exponential
# backoff. A single source hits its own hard bucket first, so one client cannot
# cheaply keep an account globally locked, while rotating sources still share a
# common budget.
ACCOUNT_LOCKOUT_PROGRESSIVE_START = 6
ACCOUNT_LOCKOUT_BASE_SECONDS = 5
ACCOUNT_LOCKOUT_MAX_SECONDS = 15 * 60
ACCOUNT_LOCKOUT_FAIL_CAP = 32
AUTH_USERNAME_MAX_LENGTH = 128
AUTH_PASSWORD_MAX_LENGTH = 1024
CLIENT_IDENTITY_MAX_LENGTH = 128
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_LOCKOUT_KEY_RE = re.compile(r"^v2:[0-9a-f]{64}$")
_logger = logging.getLogger(__name__)


def _bounded_lockout_limit() -> int:
    try:
        configured = int(os.getenv("LAWVER_LOCKOUT_MAX_RECORDS", "4096") or 4096)
    except ValueError:
        configured = 4096
    return min(max(configured, 64), 100_000)


LOCKOUT_MAX_RECORDS = _bounded_lockout_limit()
LOCKOUT_FILE_MAX_BYTES = max(64 * 1024, LOCKOUT_MAX_RECORDS * 512)
INSECURE_DEFAULT_ADMIN_HASH = (
    "cf632ecdd2c9b4e67cd76de4db6b785d$"
    "12b8bd1ec5414d7a46abf6b92a4bc0319ca7b9662bba71bc9776dcbefc4c0177"
)


def _get_required_secret_key() -> str:
    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set before starting Lawver.")
    if len(secret_key) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters long.")
    return secret_key


SECRET_KEY = _get_required_secret_key()

DATA_DIR = os.environ.get("LAWVER_DATA_DIR") or os.path.join(os.getcwd(), "data")
ACCOUNT_FILE = os.path.join(DATA_DIR, "account.json")
LOCKOUT_FILE = os.path.join(DATA_DIR, "lockout.json")
AUTH_STATE_LOCK_FILE = os.path.join(DATA_DIR, ".auth_state.lock")
_AUTH_STATE_LOCK = threading.RLock()
_AUTH_STATE_LOCK_DEPTH = threading.local()


def _ensure_private_dir(path: str) -> None:
    os.makedirs(path, mode=PRIVATE_DIR_MODE, exist_ok=True)
    os.chmod(path, PRIVATE_DIR_MODE)


def _harden_private_file(path: str) -> None:
    try:
        os.chmod(path, PRIVATE_FILE_MODE)
    except FileNotFoundError:
        return


_ensure_private_dir(DATA_DIR)


# Unknown and locked accounts still perform one password KDF, keeping the public
# failure path materially similar without persisting attacker-controlled names.
_DUMMY_PASSWORD_HASH = hash_password("lawver-dummy-login-password")


@contextmanager
def _auth_state_lock():
    _ensure_private_dir(DATA_DIR)
    with _AUTH_STATE_LOCK:
        depth = getattr(_AUTH_STATE_LOCK_DEPTH, "value", 0)
        if depth:
            _AUTH_STATE_LOCK_DEPTH.value = depth + 1
            try:
                yield
            finally:
                _AUTH_STATE_LOCK_DEPTH.value = depth
            return

        lock_fd = os.open(
            AUTH_STATE_LOCK_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            PRIVATE_FILE_MODE,
        )
        os.fchmod(lock_fd, PRIVATE_FILE_MODE)
        with os.fdopen(lock_fd, "a", encoding="utf-8") as lock_file:
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
    parent = os.path.dirname(path) or "."
    _ensure_private_dir(parent)
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        os.fchmod(fd, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        _harden_private_file(path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _ensure_account_file():
    with _auth_state_lock():
        if os.path.exists(ACCOUNT_FILE):
            _harden_private_file(ACCOUNT_FILE)
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
        if len(initial_password) > AUTH_PASSWORD_MAX_LENGTH:
            raise RuntimeError(
                f"INITIAL_ADMIN_PASSWORD must be at most {AUTH_PASSWORD_MAX_LENGTH} characters long."
            )
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
            _harden_private_file(ACCOUNT_FILE)
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


def _account_auth_version(user_data) -> int:
    if not isinstance(user_data, dict):
        return 0
    try:
        return max(int(user_data.get("auth_version", 0)), 0)
    except (TypeError, ValueError):
        return 0


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

    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return False, f"用户名长度必须为 1-{AUTH_USERNAME_MAX_LENGTH} 个字符"
    if not isinstance(password, str) or len(password) > AUTH_PASSWORD_MAX_LENGTH:
        return False, f"密码长度不能超过 {AUTH_PASSWORD_MAX_LENGTH} 位"
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, "密码长度不能小于6位"

    with _auth_state_lock():
        accounts = get_accounts_data()

        if username in accounts and accounts[username].get("role") == "admin" and normalized_role != "admin":
            return False, "不能将管理员账号降级为普通用户"

        previous_auth_version = _account_auth_version(accounts.get(username))
        accounts[username] = {
            "hash": hash_password(password),
            "role": normalized_role,
            "auth_version": previous_auth_version + 1,
        }

        try:
            _write_json(ACCOUNT_FILE, accounts)
            return True, "操作成功"
        except Exception:
            _logger.exception("Failed to persist account update")
            return False, "保存账号失败，请稍后重试"


def delete_account(username: str) -> tuple[bool, str]:
    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return False, "账号不存在"
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
        except Exception:
            _logger.exception("Failed to persist account deletion")
            return False, "删除账号失败，请稍后重试"


def create_token(username: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode("utf-8").rstrip("=")
    user_data = get_accounts_data().get(username)
    payload_dict = {
        "sub": username,
        "exp": int(time.time()) + 7 * 24 * 3600,
        "ver": _account_auth_version(user_data),
    }
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
        username = payload_dict["sub"]
        if not isinstance(username, str) or not username:
            return None
        user_data = get_accounts_data().get(username)
        if not user_data:
            return None
        try:
            token_auth_version = int(payload_dict.get("ver", 0))
        except (TypeError, ValueError):
            return None
        if token_auth_version != _account_auth_version(user_data):
            return None
        return username
    except Exception:
        return None


def _lockout_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _account_lockout_key(username: str) -> str:
    username_value = username[:AUTH_USERNAME_MAX_LENGTH]
    return f"v2:{_lockout_digest(f'account\0{username_value}')}"


def _client_lockout_key(username: str, client_identity: str) -> str:
    username_value = username[:AUTH_USERNAME_MAX_LENGTH]
    client_value = str(client_identity or "unknown")[:CLIENT_IDENTITY_MAX_LENGTH]
    return f"v2:{_lockout_digest(f'client\0{username_value}\0{client_value}')}"


def _lockout_key(username: str, client_identity: str) -> str:
    """Compatibility alias for the username/client bucket key."""
    return _client_lockout_key(username, client_identity)


def _sanitize_lockouts(raw: object, now: float) -> tuple[dict, bool]:
    if not isinstance(raw, dict):
        return {}, True

    candidates: list[tuple[float, str, dict]] = []
    dirty = False
    for key, record in raw.items():
        if not isinstance(key, str) or not _LOCKOUT_KEY_RE.fullmatch(key) or not isinstance(record, dict):
            dirty = True
            continue
        try:
            fails = min(max(int(record.get("fails", 0)), 0), ACCOUNT_LOCKOUT_FAIL_CAP)
            first_failed_at = float(record.get("first_failed_at", 0))
            last_failed_at = float(record.get("last_failed_at", first_failed_at))
            locked_until = float(record.get("locked_until", 0))
        except (TypeError, ValueError, OverflowError):
            dirty = True
            continue

        first_failed_at = min(max(first_failed_at, 0), now)
        last_failed_at = min(max(last_failed_at, first_failed_at), now)
        locked_until = min(max(locked_until, 0), now + LOCKOUT_SECONDS)
        is_locked = locked_until > now
        is_recent_failure = last_failed_at > 0 and now - last_failed_at <= LOCKOUT_WINDOW_SECONDS
        if not is_locked and not is_recent_failure:
            dirty = True
            continue

        clean_record = {
            "fails": fails,
            "first_failed_at": first_failed_at,
            "last_failed_at": last_failed_at,
            "locked_until": locked_until,
        }
        if clean_record != record:
            dirty = True
        candidates.append((max(last_failed_at, locked_until), key, clean_record))

    if len(candidates) > LOCKOUT_MAX_RECORDS:
        dirty = True
        candidates.sort(reverse=True)
        candidates = candidates[:LOCKOUT_MAX_RECORDS]

    return {key: record for _, key, record in candidates}, dirty


def _read_lockouts() -> dict:
    with _auth_state_lock():
        if not os.path.exists(LOCKOUT_FILE):
            return {}
        try:
            _harden_private_file(LOCKOUT_FILE)
            if os.path.getsize(LOCKOUT_FILE) > LOCKOUT_FILE_MAX_BYTES:
                return {}
            with open(LOCKOUT_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            lockouts, dirty = _sanitize_lockouts(raw, time.time())
            if dirty:
                _write_json(LOCKOUT_FILE, lockouts)
            return lockouts
        except Exception:
            return {}


def _write_lockouts(lockouts: dict):
    with _auth_state_lock():
        _write_json(LOCKOUT_FILE, lockouts)


def check_lockout(username: str, client_identity: str = "unknown") -> Optional[str]:
    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return None
    keys = (
        _account_lockout_key(username),
        _client_lockout_key(username, client_identity),
    )
    with _auth_state_lock():
        lockouts = _read_lockouts()

    now = time.time()
    locked_until = max(
        (float(lockouts.get(key, {}).get("locked_until", 0)) for key in keys),
        default=0,
    )
    if locked_until > now:
        remain = int((locked_until - now) / 60) + 1
        return f"账户已被锁定，请 {remain} 分钟后再试。"
    return None


def _new_lockout_record(now: float) -> dict:
    return {
        "fails": 0,
        "locked_until": 0,
        "first_failed_at": now,
        "last_failed_at": now,
    }


def _record_bucket_failure(record: object, now: float, *, progressive: bool) -> dict:
    if not isinstance(record, dict):
        record = _new_lockout_record(now)
    else:
        record = dict(record)

    first_failed_at = float(record.get("first_failed_at", now))
    last_failed_at = float(record.get("last_failed_at", first_failed_at))
    locked_until = float(record.get("locked_until", 0))
    if locked_until > now:
        return record
    if now - last_failed_at > LOCKOUT_WINDOW_SECONDS or (
        not progressive and locked_until > 0 and locked_until <= now
    ):
        record = _new_lockout_record(now)

    record["fails"] = min(int(record.get("fails", 0)) + 1, ACCOUNT_LOCKOUT_FAIL_CAP)
    record["last_failed_at"] = now
    record.setdefault("first_failed_at", now)

    if progressive:
        if record["fails"] >= ACCOUNT_LOCKOUT_PROGRESSIVE_START:
            step = min(record["fails"] - ACCOUNT_LOCKOUT_PROGRESSIVE_START, 20)
            delay = min(ACCOUNT_LOCKOUT_BASE_SECONDS * (2 ** step), ACCOUNT_LOCKOUT_MAX_SECONDS)
            record["locked_until"] = int(now + delay)
        else:
            record["locked_until"] = 0
    elif record["fails"] >= LOCKOUT_FAIL_LIMIT:
        record["locked_until"] = int(now + LOCKOUT_SECONDS)

    return record


def record_login_attempt(
    username: str,
    success: bool,
    client_identity: str = "unknown",
    *,
    account_exists: Optional[bool] = None,
):
    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return
    try:
        with _auth_state_lock():
            if account_exists is None:
                account_exists = username in get_accounts_data()
            if not account_exists:
                return

            now = time.time()
            lockouts = _read_lockouts()
            account_key = _account_lockout_key(username)
            client_key = _client_lockout_key(username, client_identity)

            if success:
                if account_key not in lockouts and client_key not in lockouts:
                    return
                lockouts.pop(account_key, None)
                lockouts.pop(client_key, None)
            else:
                lockouts[account_key] = _record_bucket_failure(
                    lockouts.get(account_key),
                    now,
                    progressive=True,
                )
                lockouts[client_key] = _record_bucket_failure(
                    lockouts.get(client_key),
                    now,
                    progressive=False,
                )

            lockouts, _ = _sanitize_lockouts(lockouts, now)

            _write_lockouts(lockouts)
    except Exception:
        _logger.exception("Failed to record login attempt")


def _upgrade_password_hash(username: str, password: str, previous_hash: str) -> None:
    """登录成功后把旧格式/低迭代摘要就地升级，失败不影响本次登录。"""
    with _auth_state_lock():
        accounts = get_accounts_data()
        user_data = accounts.get(username)
        if not isinstance(user_data, dict) or user_data.get("hash") != previous_hash:
            return
        user_data["hash"] = hash_password(password)
        _write_json(ACCOUNT_FILE, accounts)


def authenticate_user(username, password, client_identity: str = "unknown"):
    accounts = get_accounts_data()
    if not accounts:
        return False, "账号系统配置错误，请联系管理员"

    if (
        not isinstance(username, str)
        or not username
        or len(username) > AUTH_USERNAME_MAX_LENGTH
        or not isinstance(password, str)
        or len(password) > AUTH_PASSWORD_MAX_LENGTH
    ):
        verify_password("", _DUMMY_PASSWORD_HASH)
        return False, "用户名或密码错误"

    user_data = accounts.get(username)
    if not isinstance(user_data, dict):
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False, "用户名或密码错误"

    lock_msg = check_lockout(username, client_identity)
    if lock_msg:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False, "用户名或密码错误"

    hashed = user_data.get("hash")
    if verify_password(password, hashed):
        record_login_attempt(username, True, client_identity, account_exists=True)
        if password_needs_rehash(hashed):
            try:
                _upgrade_password_hash(username, password, hashed)
            except Exception:
                _logger.exception("Failed to upgrade password hash for %s", username)
        return True, "登录成功"

    record_login_attempt(username, False, client_identity, account_exists=True)
    return False, "用户名或密码错误"
