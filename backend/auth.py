"""
模块描述：账号认证与会话模块，负责密码哈希、登录锁定、权限层级与在线设备限制。

账号与密码摘要存放在 SQLite（infra/auth_store.py），首次启动会把遗留的
data/account.json 导入数据库并改名归档。角色分为 sudo / admin / user 三级：
sudo 拥有全部权限，admin 只能管理自己创建的 user（数量上限 n），user 仅使用。
"""

import os
import json
import time
import hmac
import hashlib
import base64
import logging
import re
import secrets
import threading
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv

from infra import auth_store, bloom
from infra.password_hashing import (
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

ROLE_SUDO = "sudo"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
VALID_ROLES = (ROLE_SUDO, ROLE_ADMIN, ROLE_USER)
# 系统内置的最高权限账号：用户名保持 admin 不变，角色升级为 sudo。
BUILTIN_SUDO_USERNAME = "admin"
MAX_ONLINE_LIMIT = 1000
MAX_USERS_QUOTA = 10_000
_UNLIMITED_ONLINE = 0
_UNLIMITED_USERS = -1

_LOCKOUT_KEY_RE = re.compile(r"^v2:[0-9a-f]{64}$")
_logger = logging.getLogger(__name__)


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.getenv(name, str(default)) or default)
    except ValueError:
        configured = default
    return min(max(configured, minimum), maximum)


def _bounded_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        configured = float(os.getenv(name, str(default)) or default)
    except ValueError:
        configured = default
    return min(max(configured, minimum), maximum)


ONLINE_WINDOW_SECONDS = _bounded_env_int("LAWVER_ONLINE_WINDOW_SECONDS", 15 * 60, 60, 24 * 3600)
SESSION_TTL_SECONDS = 7 * 24 * 3600
SESSION_TOUCH_INTERVAL_SECONDS = 60
# 会话布隆过滤器：用一张短位图挡掉「确定不存在」的 sid，避免伪造/过期/已注销 token
# 的洪水每个请求都打开一次 SQLite。位图只增不删、未就绪即放行，假阴性不会发生。
BLOOM_SESSION_CAPACITY = _bounded_env_int("LAWVER_BLOOM_SESSION_CAPACITY", 200_000, 1_000, 20_000_000)
BLOOM_ERROR_RATE = _bounded_env_float("LAWVER_BLOOM_ERROR_RATE", 0.001, 1e-6, 0.1)
BLOOM_WARM_RETRY_SECONDS = 60.0
ONLINE_LIMIT_ACTION = (
    os.getenv("LAWVER_ONLINE_LIMIT_ACTION", auth_store.ONLINE_LIMIT_ACTION_KICK).strip().lower()
)
if ONLINE_LIMIT_ACTION not in {
    auth_store.ONLINE_LIMIT_ACTION_KICK,
    auth_store.ONLINE_LIMIT_ACTION_REJECT,
}:
    ONLINE_LIMIT_ACTION = auth_store.ONLINE_LIMIT_ACTION_KICK


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
    except OSError:
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
    """遗留 JSON 写入工具，仅锁定状态与测试兼容路径仍在用。"""
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


# ─── 迁移与引导 ────────────────────────────────────────────────────────────


def _archive_legacy_account_file() -> None:
    """导入完成后把 account.json 改名归档，避免继续被误认为权威数据源。"""
    if not os.path.exists(ACCOUNT_FILE):
        return
    archived = f"{ACCOUNT_FILE}.imported-{int(time.time())}"
    try:
        os.replace(ACCOUNT_FILE, archived)
        _harden_private_file(archived)
        _logger.warning("已将遗留账号文件归档为 %s，账号现由 SQLite 管理。", archived)
    except OSError:
        _logger.exception("归档遗留账号文件失败，已忽略该文件。")


def _import_legacy_accounts(accounts: dict) -> None:
    promoted: list[str] = []
    for username, raw in accounts.items():
        if not isinstance(username, str) or not username:
            continue
        if isinstance(raw, str):
            record_hash = raw
            legacy_role = ROLE_SUDO if username == BUILTIN_SUDO_USERNAME else ROLE_USER
            auth_version = 0
        elif isinstance(raw, dict):
            record_hash = raw.get("hash")
            raw_role = raw.get("role", ROLE_USER)
            # 旧版 admin 等级对应新的 sudo。
            legacy_role = ROLE_SUDO if raw_role == "admin" else raw_role
            if legacy_role not in VALID_ROLES:
                legacy_role = ROLE_USER
            try:
                auth_version = max(int(raw.get("auth_version", 0)), 0)
            except (TypeError, ValueError):
                auth_version = 0
        else:
            continue
        if not isinstance(record_hash, str) or not record_hash:
            continue
        try:
            auth_store.insert_user_record(
                {
                    "username": username,
                    "password_hash": record_hash,
                    "role": legacy_role,
                    "auth_version": auth_version,
                    "owner": None,
                    "max_online": None,
                    "max_users": None,
                    "user_max_online": None,
                }
            )
            if legacy_role == ROLE_SUDO and username != BUILTIN_SUDO_USERNAME:
                promoted.append(username)
        except Exception:
            _logger.exception("导入遗留账号 %s 失败，已跳过。", username)
    if promoted:
        _logger.warning("以下遗留管理员账号已提升为 sudo，请确认是否符合预期：%s", ", ".join(promoted))


def _bootstrap_initial_admin() -> None:
    initial_password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    if not initial_password:
        raise RuntimeError(
            "No account database exists. Set INITIAL_ADMIN_PASSWORD once to bootstrap the admin account."
        )
    if len(initial_password) < PASSWORD_MIN_LENGTH:
        raise RuntimeError(f"INITIAL_ADMIN_PASSWORD must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if len(initial_password) > AUTH_PASSWORD_MAX_LENGTH:
        raise RuntimeError(
            f"INITIAL_ADMIN_PASSWORD must be at most {AUTH_PASSWORD_MAX_LENGTH} characters long."
        )
    if initial_password == "password":
        raise RuntimeError("INITIAL_ADMIN_PASSWORD cannot use the old insecure default password.")

    auth_store.insert_user_record(
        {
            "username": BUILTIN_SUDO_USERNAME,
            "password_hash": hash_password(initial_password),
            "role": ROLE_SUDO,
            "auth_version": 0,
            "owner": None,
            "max_online": None,
            "max_users": None,
            "user_max_online": None,
        }
    )


def _reject_insecure_default_admin() -> None:
    admin = auth_store.get_user(BUILTIN_SUDO_USERNAME)
    if admin and admin.get("password_hash") == INSECURE_DEFAULT_ADMIN_HASH:
        raise RuntimeError(
            "Insecure default admin account detected. Replace the auth database or bootstrap a new admin password."
        )


def _ensure_auth_store() -> None:
    with _auth_state_lock():
        auth_store.ensure_schema()
        if auth_store.count_users() == 0:
            legacy = _read_legacy_accounts()
            if legacy:
                _import_legacy_accounts(legacy)
                _archive_legacy_account_file()
            else:
                _bootstrap_initial_admin()
        _reject_insecure_default_admin()
        auth_store.harden_storage()


def _read_legacy_accounts() -> dict:
    if not os.path.exists(ACCOUNT_FILE):
        return {}
    try:
        _harden_private_file(ACCOUNT_FILE)
        with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        _logger.exception("读取遗留账号文件失败，将按无账号文件处理。")
        return {}


def _ensure_account_file():
    """兼容旧调用：加固认证存储目录与遗留账号文件权限。"""
    with _auth_state_lock():
        _ensure_private_dir(DATA_DIR)
        auth_store.harden_storage()
        _harden_private_file(ACCOUNT_FILE)


_ensure_auth_store()


# ─── 账号读取 ──────────────────────────────────────────────────────────────


def _account_auth_version(user_data) -> int:
    if not isinstance(user_data, dict):
        return 0
    try:
        return max(int(user_data.get("auth_version", 0)), 0)
    except (TypeError, ValueError):
        return 0


def get_user_record(username: str) -> Optional[dict]:
    if not isinstance(username, str) or not username:
        return None
    return auth_store.get_user(username)


def get_accounts_data() -> dict:
    """兼容旧接口：返回 {username: {hash, role, auth_version}} 视图。"""
    return {
        record["username"]: {
            "hash": record["password_hash"],
            "role": record["role"],
            "auth_version": int(record.get("auth_version", 0)),
        }
        for record in auth_store.get_all_users()
    }


def get_user_role(username: str) -> str:
    record = get_user_record(username)
    if record and record.get("role") in VALID_ROLES:
        return record["role"]
    return ROLE_USER


def get_user_limits(username: str) -> dict:
    record = get_user_record(username) or {}
    return {
        "max_online": record.get("max_online"),
        "max_users": record.get("max_users"),
        "user_max_online": record.get("user_max_online"),
    }


def count_online(username: str) -> int:
    return auth_store.count_online(username, online_window=ONLINE_WINDOW_SECONDS)


def list_accounts(actor: Optional[str] = None) -> list:
    """列出租户内可见账号；admin 只看名下 user，user 看不到任何账号。"""
    actor_role = get_user_role(actor) if actor else ROLE_SUDO
    if actor and actor_role == ROLE_USER:
        return []
    records = auth_store.get_all_users()
    if actor and actor_role == ROLE_ADMIN:
        records = [record for record in records if record.get("owner") == actor]

    names = [record["username"] for record in records]
    online = auth_store.online_counts(names, online_window=ONLINE_WINDOW_SECONDS)
    result = []
    for record in records:
        username = record["username"]
        owned_count = None
        if record["role"] == ROLE_ADMIN:
            owned_count = auth_store.count_owned_users(username)
        result.append(
            {
                "username": username,
                "role": record["role"],
                "owner": record.get("owner"),
                "max_online": record.get("max_online"),
                "max_users": record.get("max_users"),
                "user_max_online": record.get("user_max_online"),
                "online_count": online.get(username, 0),
                "owned_count": owned_count,
                "created_at": record.get("created_at"),
                "updated_at": record.get("updated_at"),
            }
        )
    return result


# ─── 账号写入 ──────────────────────────────────────────────────────────────


def _validate_online_value(value, *, allow_unlimited: bool, label: str) -> tuple[bool, str, Optional[int]]:
    if value is None:
        return True, "", None
    if not isinstance(value, int) or isinstance(value, bool):
        return False, f"{label}必须是整数", None
    if allow_unlimited and value == _UNLIMITED_ONLINE:
        return True, "", None
    if value < 1 or value > MAX_ONLINE_LIMIT:
        return False, f"{label}必须在 1-{MAX_ONLINE_LIMIT} 之间，0 表示不限制", None
    return True, "", value


def _validate_users_quota(value) -> tuple[bool, str, Optional[int]]:
    if value is None:
        return True, "", None
    if not isinstance(value, int) or isinstance(value, bool):
        return False, "用户数量上限必须是整数", None
    if value == _UNLIMITED_USERS:
        return True, "", None
    if value < 0 or value > MAX_USERS_QUOTA:
        return False, f"用户数量上限必须在 0-{MAX_USERS_QUOTA} 之间，-1 表示不限制", None
    return True, "", value


def upsert_account(
    actor: str,
    username: str,
    password: str,
    role: Optional[str] = None,
    max_online: Optional[int] = None,
    max_users: Optional[int] = None,
    user_max_online: Optional[int] = None,
) -> tuple[bool, str]:
    """创建或更新账号。role/limit 传 None 表示「沿用原值」（新建时表示不限）。"""
    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return False, f"用户名长度必须为 1-{AUTH_USERNAME_MAX_LENGTH} 个字符"
    if not isinstance(password, str) or len(password) > AUTH_PASSWORD_MAX_LENGTH:
        return False, f"密码长度不能超过 {AUTH_PASSWORD_MAX_LENGTH} 位"
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, "密码长度不能小于6位"
    if not isinstance(actor, str) or not actor:
        return False, "调用者身份无效"

    actor_role = get_user_role(actor)
    if actor_role not in (ROLE_SUDO, ROLE_ADMIN):
        return False, "权限不足"

    ok, message, normalized_online = _validate_online_value(
        max_online, allow_unlimited=True, label="最大在线数量"
    )
    if not ok:
        return False, message
    ok, message, normalized_user_online = _validate_online_value(
        user_max_online, allow_unlimited=True, label="用户默认最大在线数量"
    )
    if not ok:
        return False, message
    ok, message, normalized_max_users = _validate_users_quota(max_users)
    if not ok:
        return False, message

    requested_role = role
    if requested_role is not None and requested_role not in VALID_ROLES:
        return False, "角色不合法"

    with _auth_state_lock():
        existing = auth_store.get_user(username)

        actor_record = auth_store.get_user(actor) or {}
        inherited_online: Optional[int] = None
        if actor_role == ROLE_ADMIN:
            if requested_role not in (None, ROLE_USER):
                return False, "管理员只能创建普通用户"
            if any(value is not None for value in (max_online, max_users, user_max_online)):
                return False, "管理员不能设置最大在线数量"
            if existing is not None and existing.get("owner") != actor:
                return False, "只能管理自己创建的账号"
            if existing is None:
                owner = actor
                quota = actor_record.get("max_users")
                if quota is not None and auth_store.count_owned_users(actor) >= int(quota):
                    return False, f"已达可创建用户上限（{quota} 个），请联系超级管理员调整"
            else:
                owner = existing.get("owner")
            effective_role = ROLE_USER
            # admin 创建的 user 继承该 admin 的 m（user_max_online），且不可自行修改。
            inherited_online = actor_record.get("user_max_online")
        else:
            if (
                username == BUILTIN_SUDO_USERNAME
                and existing is not None
                and requested_role not in (None, ROLE_SUDO)
            ):
                return False, "不能将管理员账号降级"
            if (
                username == actor
                and existing is not None
                and requested_role is not None
                and requested_role != existing.get("role")
            ):
                return False, "不能修改自己的角色"
            owner = existing.get("owner") if existing else None
            effective_role = requested_role or (existing.get("role") if existing else ROLE_USER)
            if effective_role not in VALID_ROLES:
                effective_role = ROLE_USER

        try:
            if existing is None:
                if actor_role == ROLE_ADMIN:
                    new_max_online = inherited_online
                    new_max_users = None
                    new_user_max_online = None
                else:
                    new_max_online = normalized_online
                    new_max_users = normalized_max_users
                    new_user_max_online = normalized_user_online
                auth_store.insert_user_record(
                    {
                        "username": username,
                        "password_hash": hash_password(password),
                        "role": effective_role,
                        "auth_version": 0,
                        "owner": owner,
                        "max_online": new_max_online,
                        "max_users": new_max_users,
                        "user_max_online": new_user_max_online,
                    }
                )
            else:
                updates: dict = {
                    "password_hash": hash_password(password),
                    "auth_version": _account_auth_version(existing) + 1,
                }
                if requested_role is not None:
                    updates["role"] = effective_role
                if max_online is not None and actor_role == ROLE_SUDO:
                    updates["max_online"] = normalized_online
                if max_users is not None and actor_role == ROLE_SUDO:
                    updates["max_users"] = normalized_max_users
                if user_max_online is not None and actor_role == ROLE_SUDO:
                    updates["user_max_online"] = normalized_user_online
                auth_store.update_user(username, **updates)
        except Exception:
            _logger.exception("保存账号失败：%s", username)
            return False, "保存账号失败，请稍后重试"

        # 密码或角色变化后立刻作废旧会话，避免旧令牌继续生效。
        try:
            auth_store.revoke_user_sessions(username)
        except Exception:
            _logger.exception("清理账号会话失败：%s", username)

    return True, "操作成功"


def add_or_update_account(username: str, password: str, role: str = ROLE_USER) -> tuple[bool, str]:
    """兼容旧签名：以 sudo 身份创建/更新账号。"""
    return upsert_account(BUILTIN_SUDO_USERNAME, username, password, role=role)


def set_account_limits(
    actor: str,
    username: str,
    max_online: Optional[int] = None,
    max_users: Optional[int] = None,
    user_max_online: Optional[int] = None,
) -> tuple[bool, str]:
    if get_user_role(actor) != ROLE_SUDO:
        return False, "只有超级管理员可以调整配额"
    target = auth_store.get_user(username)
    if target is None:
        return False, "账号不存在"

    ok, message, normalized_online = _validate_online_value(
        max_online, allow_unlimited=True, label="最大在线数量"
    )
    if not ok:
        return False, message
    ok, message, normalized_user_online = _validate_online_value(
        user_max_online, allow_unlimited=True, label="用户默认最大在线数量"
    )
    if not ok:
        return False, message
    ok, message, normalized_max_users = _validate_users_quota(max_users)
    if not ok:
        return False, message

    updates: dict = {}
    if max_online is not None:
        updates["max_online"] = normalized_online
    if max_users is not None:
        updates["max_users"] = normalized_max_users
    if user_max_online is not None:
        updates["user_max_online"] = normalized_user_online
    if not updates:
        return True, "未做任何修改"

    try:
        if not auth_store.update_user(username, **updates):
            return False, "账号不存在"
    except Exception:
        _logger.exception("更新账号配额失败：%s", username)
        return False, "保存失败，请稍后重试"
    return True, "配额已更新"


def delete_account(username: str, actor: Optional[str] = None) -> tuple[bool, str]:
    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return False, "账号不存在"
    if username == BUILTIN_SUDO_USERNAME:
        return False, "不能删除系统管理员账号"
    if actor and username == actor:
        return False, "不能删除自己的账号"

    actor_role = get_user_role(actor) if actor else ROLE_SUDO
    if actor and actor_role not in (ROLE_SUDO, ROLE_ADMIN):
        return False, "权限不足"

    with _auth_state_lock():
        target = auth_store.get_user(username)
        if target is None:
            return False, "账号不存在"
        if actor_role == ROLE_ADMIN and target.get("owner") != actor:
            return False, "只能删除自己创建的账号"

        try:
            auth_store.revoke_user_sessions(username)
            auth_store.delete_user_row(username)
            return True, "账号已删除"
        except Exception:
            _logger.exception("删除账号失败：%s", username)
            return False, "删除账号失败，请稍后重试"


# ─── 令牌与会话 ────────────────────────────────────────────────────────────


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(header: str, payload: str) -> str:
    return _b64url_encode(
        hmac.new(SECRET_KEY.encode("utf-8"), f"{header}.{payload}".encode("utf-8"), hashlib.sha256).digest()
    )


def create_token(username: str, sid: str) -> str:
    header = _b64url_encode(b'{"alg":"HS256","typ":"JWT"}')
    user_data = auth_store.get_user(username)
    payload_dict = {
        "sub": username,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
        "ver": _account_auth_version(user_data),
        "sid": sid,
    }
    payload = _b64url_encode(json.dumps(payload_dict).encode("utf-8"))
    return f"{header}.{payload}.{_signature(header, payload)}"


def decode_token(token: str) -> Optional[dict]:
    """校验签名与过期时间，返回 claims；不校验账号/会话状态。"""
    if not token:
        return None
    try:
        header, payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _signature(header, payload)):
            return None
        payload_dict = json.loads(_b64url_decode(payload))
        if float(payload_dict["exp"]) < time.time():
            return None
        return payload_dict
    except Exception:
        return None


_SESSION_TOUCH_LOCK = threading.Lock()
_LAST_SESSION_TOUCH: dict[str, float] = {}


def _touch_session(sid: str, now: float) -> None:
    """节流刷新在线时间，避免每个请求都写库。"""
    with _SESSION_TOUCH_LOCK:
        last = _LAST_SESSION_TOUCH.get(sid)
        if last is not None and now - last < SESSION_TOUCH_INTERVAL_SECONDS:
            return
        _LAST_SESSION_TOUCH[sid] = now
        if len(_LAST_SESSION_TOUCH) > 8192:
            cutoff = now - SESSION_TTL_SECONDS
            for key in [key for key, value in _LAST_SESSION_TOUCH.items() if value < cutoff]:
                _LAST_SESSION_TOUCH.pop(key, None)
    try:
        auth_store.touch_session(sid, now=now)
    except Exception:
        _logger.exception("刷新会话活跃时间失败")


# ─── 会话布隆过滤器 ────────────────────────────────────────────────────────

_bloom_lock = threading.Lock()
_session_bloom = None
_last_bloom_warm_attempt = 0.0


def session_bloom():
    """惰性创建会话布隆过滤器：Redis 可用时用共享位图，否则退回进程内位图。"""
    global _session_bloom
    if _session_bloom is not None:
        return _session_bloom
    with _bloom_lock:
        if _session_bloom is None:
            _session_bloom = bloom.create(
                "session",
                capacity=BLOOM_SESSION_CAPACITY,
                error_rate=BLOOM_ERROR_RATE,
            )
    return _session_bloom


def warm_session_bloom() -> int:
    """用数据库里仍然有效的 sid 预热位图；失败就保持未就绪，读取端会继续回源。"""
    filter_ = session_bloom()
    try:
        rows = auth_store.list_sessions(
            usernames=None,
            online_window=ONLINE_WINDOW_SECONDS,
            online_only=False,
        )
    except Exception:
        _logger.exception("读取会话列表失败，布隆过滤器保持未就绪")
        return 0
    return filter_.warm(row.get("sid") for row in rows if row.get("sid"))


def _schedule_session_bloom_warm() -> None:
    """未就绪时在后台补一次预热；同进程内限频，避免请求路径反复触发。"""
    global _last_bloom_warm_attempt
    now = time.time()
    if now - _last_bloom_warm_attempt < BLOOM_WARM_RETRY_SECONDS:
        return
    _last_bloom_warm_attempt = now

    def runner() -> None:
        try:
            warm_session_bloom()
        except Exception:
            _logger.exception("后台预热会话布隆过滤器失败")

    threading.Thread(target=runner, name="session-bloom-warm", daemon=True).start()


def _known_session(sid: str) -> tuple[bool, bool]:
    """返回 (该 sid 是否可能存在, 位图是否需要预热)。false 表示可以跳过数据库。"""
    filter_ = session_bloom()
    maybe_known = filter_.maybe_contains(sid)
    return maybe_known, filter_.needs_warm()


def bloom_status() -> dict:
    return session_bloom().status()


def verify_token(token: str) -> Optional[str]:
    payload_dict = decode_token(token)
    if not payload_dict:
        return None
    username = payload_dict.get("sub")
    if not isinstance(username, str) or not username:
        return None
    sid = payload_dict.get("sid")
    if not isinstance(sid, str) or not sid:
        return None

    maybe_known, needs_warm = _known_session(sid)
    if not maybe_known:
        # 位图确认该 sid 从未签发：直接拒绝，不打开数据库。
        return None
    if needs_warm:
        _schedule_session_bloom_warm()

    user_data = auth_store.get_user(username)
    if not user_data:
        return None
    try:
        token_auth_version = int(payload_dict.get("ver", 0))
    except (TypeError, ValueError):
        return None
    if token_auth_version != _account_auth_version(user_data):
        return None

    session = auth_store.get_session(sid)
    now = time.time()
    if not session or session.get("revoked") or session.get("username") != username:
        return None
    if float(session.get("expires_at", 0)) < now:
        return None

    _touch_session(sid, now)
    return username


def create_session(
    username: str,
    *,
    client: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip_hash: Optional[str] = None,
) -> tuple[bool, str, Optional[str], list[str]]:
    """登记一台在线设备，返回 (是否成功, 提示, sid, 被踢会话列表)。"""
    record = auth_store.get_user(username)
    if record is None:
        return False, "账号不存在", None, []
    sid = secrets.token_urlsafe(32)
    ok, message, evicted = auth_store.reserve_session(
        sid=sid,
        username=username,
        max_online=record.get("max_online"),
        limit_action=ONLINE_LIMIT_ACTION,
        ttl_seconds=SESSION_TTL_SECONDS,
        online_window=ONLINE_WINDOW_SECONDS,
        client=client,
        user_agent=user_agent,
        ip_hash=ip_hash,
    )
    if not ok:
        return False, message, None, []
    try:
        session_bloom().add(sid)
    except Exception:
        # 位图写入失败只会让后续请求多查一次库，不能影响登录本身。
        _logger.exception("写入会话布隆过滤器失败：%s", sid)
    if evicted:
        _logger.warning("账号 %s 在线设备超限，已下线 %d 台最久未活跃设备。", username, len(evicted))
    return True, "登录成功", sid, evicted


def revoke_token_session(token: str) -> bool:
    payload_dict = decode_token(token)
    if not payload_dict:
        return False
    sid = payload_dict.get("sid")
    if not isinstance(sid, str) or not sid:
        return False
    if not session_bloom().maybe_contains(sid):
        # 从未签发的 sid 不必开写事务。
        return False
    return auth_store.revoke_session(sid)


def revoke_user_sessions(username: str) -> int:
    return auth_store.revoke_user_sessions(username)


def list_sessions(actor: Optional[str] = None, *, online_only: bool = False) -> list:
    actor_role = get_user_role(actor) if actor else ROLE_SUDO
    scope: Optional[list[str]] = None
    if actor and actor_role == ROLE_ADMIN:
        scope = [
            record["username"]
            for record in auth_store.get_all_users()
            if record.get("owner") == actor
        ]
    return auth_store.list_sessions(
        usernames=scope,
        online_window=ONLINE_WINDOW_SECONDS,
        online_only=online_only,
    )


def revoke_session(actor: str, sid: str) -> tuple[bool, str]:
    session = auth_store.get_session(sid)
    if session is None:
        return False, "会话不存在或已过期"
    actor_role = get_user_role(actor)
    if actor_role == ROLE_ADMIN:
        target = auth_store.get_user(session["username"])
        if target is None or target.get("owner") != actor:
            return False, "只能管理自己创建的账号"
    elif actor_role != ROLE_SUDO:
        return False, "权限不足"
    auth_store.revoke_session(sid)
    return True, "已下线该设备"


def hash_client_identity(client_ip: Optional[str]) -> Optional[str]:
    """IP 只保存摘要，避免在会话表里落原文。"""
    if not client_ip:
        return None
    return hashlib.sha256(str(client_ip).encode("utf-8")).hexdigest()[:32]


# ─── 锁定策略（沿用 JSON 存储） ────────────────────────────────────────────


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
                account_exists = auth_store.get_user(username) is not None
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
        user_data = auth_store.get_user(username)
        if not isinstance(user_data, dict) or user_data.get("password_hash") != previous_hash:
            return
        auth_store.update_user(username, password_hash=hash_password(password))


def authenticate_user(username, password, client_identity: str = "unknown"):
    if auth_store.count_users() == 0:
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

    user_data = auth_store.get_user(username)
    if not isinstance(user_data, dict):
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False, "用户名或密码错误"

    lock_msg = check_lockout(username, client_identity)
    if lock_msg:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False, "用户名或密码错误"

    hashed = user_data.get("password_hash")
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
