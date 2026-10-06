"""
模块描述：账号认证与会话模块，负责密码哈希、登录锁定、权限层级与在线设备限制。

账号与会话存在云端数据库（infra/account_store.py），与工作台内容同库，这样
「扣费 + 记账 + 账号状态」才能落在同一个事务里。首次启动会把遗留的
data/account.json 与旧 data/auth.sqlite3 导入并归档。角色分为 sudo / admin / user
三级：sudo 拥有全部权限，admin 只能管理自己创建的 user（数量上限 n），user 仅使用。

会话是**不透明 sid**，没有 JWT、没有 auth_version：撤销即删行，即时生效。
布隆过滤器挡掉「从未签发」的 sid，Redis 缓存最近验证过的会话（TTL 60 秒，
撤销时主动删除），两者都不可用时自动退回每次查库。
"""

import os
import json
import math
import time
import hmac
import hashlib
import base64
import logging
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from billing import ledger as billing_ledger
from infra import account_store as auth_store, bloom, redis_backend, throttle
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
# 节流策略的唯一出处在 infra/throttle.py（存储与算法都在那里）；
# 这里 re-export，保持既有调用点与测试的引用不变。
LOCKOUT_FAIL_LIMIT = throttle.LOCKOUT_FAIL_LIMIT
LOCKOUT_SECONDS = throttle.LOCKOUT_SECONDS
LOCKOUT_WINDOW_SECONDS = throttle.LOCKOUT_WINDOW_SECONDS
# 聚合账号桶起步更晚并做短指数退避：单一来源会先撞到自己的硬桶，
# 于是单个客户端无法廉价地把整个账号锁住，而轮换来源仍共享同一份预算。
ACCOUNT_LOCKOUT_PROGRESSIVE_START = throttle.ACCOUNT_LOCKOUT_PROGRESSIVE_START
ACCOUNT_LOCKOUT_BASE_SECONDS = throttle.ACCOUNT_LOCKOUT_BASE_SECONDS
ACCOUNT_LOCKOUT_MAX_SECONDS = throttle.ACCOUNT_LOCKOUT_MAX_SECONDS
ACCOUNT_LOCKOUT_FAIL_CAP = throttle.ACCOUNT_LOCKOUT_FAIL_CAP
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
MAX_MULTIPLIER = 100.0
MAX_INITIAL_CREDITS = 10_000_000.0
_UNLIMITED_ONLINE = 0
_UNLIMITED_USERS = -1

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


_STORE_READY = False
_STORE_LOCK = threading.Lock()


def ensure_auth_store_ready() -> None:
    """启动钩子：显式引导一次账号库；没配数据库时只记日志，不阻断启动。"""
    _ensure_auth_store()


def auth_store_ready() -> bool:
    """云端数据库是否可用；未配置时鉴权整体不可用，前端会显示「尚未就绪」。"""
    return _STORE_READY


def _ensure_auth_store() -> None:
    """确保账号表存在并完成一次性引导；首次调用才连库。

    没配数据库时**不抛异常**：介绍页、更新检查这些公开路径不该因为
    后端缺配置而整个起不来，登录时再给出明确错误。
    """
    global _STORE_READY
    if _STORE_READY:
        return
    with _STORE_LOCK:
        if _STORE_READY:
            return
        try:
            auth_store.ensure_tables()
        except (HTTPException, OperationalError) as error:
            # 只吞「连不上/没配库」：服务照常起，登录时给明确错误。
            # 引导过程中的安全类失败（例如不安全的默认管理员）必须继续冒泡。
            _logger.error("云端账号库不可用，登录与工作台将不可使用：%s", error)
            return

        if auth_store.count_users() == 0:
            legacy = _read_legacy_accounts()
            if legacy:
                _import_legacy_accounts(legacy)
                _archive_legacy_account_file()
            elif _import_sqlite_accounts():
                pass
            else:
                _bootstrap_initial_admin()
        _reject_insecure_default_admin()
        _STORE_READY = True


def _import_sqlite_accounts() -> int:
    """把旧 data/auth.sqlite3 里的账号一次性搬进云端库，成功后把文件改名归档。

    只搬账号本身；旧会话是 JWT，语义已经不存在，全部作废（所有人重新登录一次）。
    """
    source = os.path.join(DATA_DIR, "auth.sqlite3")
    if not os.path.exists(source):
        return 0
    import sqlite3

    try:
        connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM users").fetchall()
        connection.close()
    except Exception:
        _logger.exception("读取旧 SQLite 账号库失败，跳过导入。")
        return 0
    if not rows:
        return 0
    for row in rows:
        auth_store.insert_user_record(
            {
                "username": row["username"],
                "password_hash": row["password_hash"],
                "role": row["role"] if row["role"] in (ROLE_SUDO, ROLE_ADMIN, ROLE_USER) else ROLE_USER,
                "owner": row["owner"],
                "max_online": row["max_online"],
                "max_users": row["max_users"],
                "user_max_online": row["user_max_online"],
            }
        )
    try:
        os.replace(source, f"{source}.imported-{int(time.time())}")
    except OSError:
        _logger.exception("归档旧 SQLite 账号库失败。")
    _logger.warning("已从旧 SQLite 账号库导入 %d 个账号，并归档该文件。", len(rows))
    return len(rows)


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
    """加固本机仍会落盘的那点认证状态：数据目录、遗留账号文件与锁定文件。

    账号本身已经在云端库里，本机不再有 auth.sqlite3 需要收紧。
    """
    with _auth_state_lock():
        _ensure_private_dir(DATA_DIR)
        _harden_private_file(ACCOUNT_FILE)


# 惰性触发：首次真正用到账号时才连库（见 _ensure_auth_store 的说明）。


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
    _ensure_auth_store()
    return auth_store.get_user(username)


def get_accounts_data() -> dict:
    """兼容旧接口：返回 {username: {hash, role, auth_version}} 视图。"""
    _ensure_auth_store()
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


# ─── 个人资料（uid / custom_id / 头像）────────────────────────────────────
#
# uid 是账号的稳定标识（介绍页头像 URL 等对外引用一律用它）；custom_id 是用户
# 自选的展示句柄。两者都不参与鉴权——改它们不影响会话。

CUSTOM_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}[a-z0-9]$")
RESERVED_CUSTOM_IDS = frozenset(
    {
        "admin", "administrator", "root", "api", "www", "lawver", "support",
        "system", "me", "user", "users", "account", "accounts", "null",
        "undefined", "login", "logout", "settings", "home", "business",
    }
)
AVATAR_MAX_BYTES = 1 * 1024 * 1024
AVATAR_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def get_account_profile(username: str) -> Optional[dict]:
    """会话/个人资料共用的对外形状；不含任何凭据字节。

    读取前先懒应用到期的预约变更，plan/pending 字段才不会停在旧值。
    """
    apply_pending_plan_if_due(username)
    record = get_user_record(username)
    if not record:
        return None
    return {
        "username": record["username"],
        "uid": record.get("uid"),
        "custom_id": record.get("custom_id"),
        "role": record.get("role", ROLE_USER),
        "plan": record.get("plan", "metered"),
        "avatar_version": record.get("avatar_version", 0),
        "pending_plan": record.get("pending_plan"),
        "pending_effective_at": record.get("pending_effective_at"),
    }


def validate_custom_id(custom_id: str) -> Optional[str]:
    """返回人话错误；None 表示合法。"""
    value = (custom_id or "").strip().lower()
    if not CUSTOM_ID_PATTERN.fullmatch(value):
        return "自定义 ID 需 2-32 位小写字母、数字、连字符或下划线，且以字母或数字开头结尾。"
    if value in RESERVED_CUSTOM_IDS:
        return "该 ID 为保留字，请换一个。"
    return None


def update_custom_id(username: str, custom_id: Optional[str]) -> tuple[bool, str]:
    """置空表示清除。返回 (是否成功, 错误消息)。"""
    value = (custom_id or "").strip().lower() or None
    if value:
        error = validate_custom_id(value)
        if error:
            return False, error
    outcome = auth_store.set_custom_id(username, value)
    if outcome == "conflict":
        return False, "该自定义 ID 已被占用，请换一个。"
    if outcome != "ok":
        # 与其余分支同为二元组：路由按 (ok, error) 解包，多一个元素会直接 500。
        return False, "保存失败，请稍后重试。"
    return True, ""


# 套餐自服务只放行降级与切回按量；升级走客服/支付（pricing 页的口径一致）。
PLAN_RANK = {"metered": 0, "go": 1, "pro": 2, "max": 3}


def apply_pending_plan_if_due(username: str) -> Optional[str]:
    """读取路径懒应用：到结算日的预约变更在这里落地，落完返回新 plan。"""
    return auth_store.apply_pending_plan_if_due(username)


def schedule_plan_change(username: str, target_plan: str) -> tuple[bool, str, Optional[object]]:
    """预约降级/切回按量到下一结算周期。

    返回 (是否成功, 消息, 生效时间)。升级（更高档位）与 business 不在此通道——
    升级涉及支付/客服，business 由组织管理，都在定价页口径里写明。
    """
    record = get_user_record(username)
    if not record:
        return False, "账号不存在。", None
    current = record.get("plan") or "metered"
    if current == "business" or target_plan == "business":
        return False, "Business 套餐由组织管理，请编辑子账号与配额而不是变更自身套餐。", None
    if target_plan not in PLAN_RANK or current not in PLAN_RANK:
        return False, "未知的目标套餐。", None
    if PLAN_RANK[target_plan] > PLAN_RANK[current]:
        return False, "升级请通过定价页联系客服开通，这里只支持降级与切回按量。", None
    if target_plan == current:
        return False, "已经是当前套餐。", None
    # 结算日：有周期到期日按它；没有（老数据/纯按量期）按下个自然月边界。
    # 账本 dict 里的时间是 epoch 秒，写库前转回 datetime。
    effective = record.get("grant_expire_at")
    if isinstance(effective, (int, float)):
        effective = datetime.fromtimestamp(effective, tz=timezone.utc)
    if effective is None:
        now = datetime.now(timezone.utc)
        nxt = (now.replace(day=1) + timedelta(days=45)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        effective = nxt
    if not auth_store.set_pending_plan(username, target_plan, effective):
        return False, "保存失败，请稍后重试。", None
    return True, "", effective


def cancel_pending_plan(username: str) -> bool:
    """取消预约中的变更（随时可取消，当前权益不变）。"""
    return auth_store.set_pending_plan(username, None, None)


def update_avatar(username: str, data: bytes, content_type: str) -> tuple[Optional[int], str]:
    if content_type not in AVATAR_CONTENT_TYPES:
        return None, "头像仅支持 PNG / JPEG / WebP。"
    if len(data) > AVATAR_MAX_BYTES:
        return None, "头像图片需小于 1 MB。"
    if not data:
        return None, "头像文件为空。"
    return auth_store.set_avatar(username, data, content_type), ""


def clear_user_avatar(username: str) -> int:
    return auth_store.clear_avatar(username)


def get_user_avatar(username: str) -> Optional[dict]:
    return auth_store.get_avatar(username)


def get_user_avatar_by_uid(uid: str) -> Optional[dict]:
    return auth_store.get_avatar_by_uid(uid)


def count_online(username: str) -> int:
    """在线设备数：Redis 有序集合优先，不可用或为空时回落到数据库统计。"""
    now = time.time()
    cached = _redis_online_count(username, now)
    if cached:
        return cached
    return auth_store.count_online(username, online_window=ONLINE_WINDOW_SECONDS)


def list_accounts(actor: Optional[str] = None) -> list:
    _ensure_auth_store()
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
                "plan": record.get("plan", "metered"),
                "billing_cycle": record.get("billing_cycle", "prepaid"),
                "credits_balance": int(record.get("credits_balance", 0) or 0),
                "status": record.get("status", "active"),
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


def _validate_multiplier(value) -> tuple[bool, str, Optional[float]]:
    """账号级计费倍率：正数、有限、有上限，避免把定价打成 0 或天文数字。"""
    if value is None:
        return True, "", None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False, "计费倍率必须是数字", None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0 or normalized > MAX_MULTIPLIER:
        return False, f"计费倍率必须在 0-{MAX_MULTIPLIER:g} 之间", None
    return True, "", normalized


def _validate_initial_credits(value) -> tuple[bool, str, Optional[float]]:
    if value is None:
        return True, "", None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False, "开户额度必须是数字", None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0 or normalized > MAX_INITIAL_CREDITS:
        return False, f"开户额度必须在 0-{int(MAX_INITIAL_CREDITS)} 之间", None
    return True, "", normalized


def upsert_account(
    actor: str,
    username: str,
    password: str,
    role: Optional[str] = None,
    max_online: Optional[int] = None,
    max_users: Optional[int] = None,
    user_max_online: Optional[int] = None,
    plan: Optional[str] = None,
    billing_cycle: Optional[str] = None,
    credit_multiplier: Optional[float] = None,
    initial_credits: Optional[float] = None,
) -> tuple[bool, str]:
    """创建或更新账号。role/limit/计费字段传 None 表示「沿用原值」（新建时表示默认）。

    开户额度是**账本事件**：账号落库后调用 billing.ledger.grant 写入，而不是直接
    改 credits_balance——对账按账本重算余额，直接写会被下一次 reconcile 抹掉。
    """
    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return False, f"用户名长度必须为 1-{AUTH_USERNAME_MAX_LENGTH} 个字符"
    if not isinstance(password, str) or len(password) > AUTH_PASSWORD_MAX_LENGTH:
        return False, f"密码长度不能超过 {AUTH_PASSWORD_MAX_LENGTH} 位"
    if len(password) < PASSWORD_MIN_LENGTH:
        return False, "密码长度不能小于6位"
    if not isinstance(actor, str) or not actor:
        return False, "调用者身份无效"

    actor_role = get_user_role(actor)
    # 能建账号的两类人：staff（sudo/admin）与 Business 母账号（建自己的子账号）。
    # 后者走下面那条与 admin 同样严格的支线：只能建 user、只能管自己名下的。
    actor_is_business = bool(actor) and (get_user_record(actor) or {}).get("plan") == "business"
    if actor_role not in (ROLE_SUDO, ROLE_ADMIN) and not actor_is_business:
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

    if plan is not None and plan not in auth_store.VALID_PLANS:
        return False, "套餐不合法"
    if billing_cycle is not None and billing_cycle not in auth_store.VALID_BILLING_CYCLES:
        return False, "计费方式不合法"
    ok, message, normalized_multiplier = _validate_multiplier(credit_multiplier)
    if not ok:
        return False, message
    ok, message, normalized_credits = _validate_initial_credits(initial_credits)
    if not ok:
        return False, message

    requested_role = role
    if requested_role is not None and requested_role not in VALID_ROLES:
        return False, "角色不合法"

    with _auth_state_lock():
        existing = auth_store.get_user(username)

        actor_record = auth_store.get_user(actor) or {}
        inherited_online: Optional[int] = None
        # admin 与 Business 母账号都属于「代建」：新账号的在线上限继承创建者的 m，
        # 不接受调用方自带的配额。
        delegated_creator = False
        # Business 母账号建子账号：规则与 admin 建用户一致——只能建普通用户、
        # 只能管自己名下的、受自己的 max_users 约束。
        if actor_role not in (ROLE_SUDO, ROLE_ADMIN) and actor_record.get("plan") == "business":
            if requested_role not in (None, ROLE_USER):
                return False, "子账号只能是普通用户"
            if existing is not None and existing.get("owner") != actor:
                return False, "只能管理自己创建的账号"
            if existing is None:
                quota = actor_record.get("max_users")
                if quota is not None and auth_store.count_owned_users(actor) >= int(quota):
                    return False, f"已达子账号上限（{quota} 个），请联系客服调整"
            owner = existing.get("owner") if existing else actor
            effective_role = ROLE_USER
            inherited_online = actor_record.get("user_max_online")
            delegated_creator = True
        elif actor_role == ROLE_ADMIN:
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
            delegated_creator = True
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

        created = existing is None
        try:
            if created:
                if delegated_creator:
                    new_max_online = inherited_online
                    new_max_users = None
                    new_user_max_online = None
                else:
                    new_max_online = normalized_online
                    new_max_users = normalized_max_users
                    new_user_max_online = normalized_user_online
                record = {
                    "username": username,
                    "password_hash": hash_password(password),
                    "role": effective_role,
                    "owner": owner,
                    "max_online": new_max_online,
                    "max_users": new_max_users,
                    "user_max_online": new_user_max_online,
                }
                # 计费字段与更新路径同口径（见下面 879 行注释）：只有 sudo 能在开户时
                # 指定套餐/计费方式/倍率，否则 admin 建号通道可以铸造 business 子账号
                # 或把倍率打到近 0 绕过计价。
                if actor_role == ROLE_SUDO:
                    if plan is not None:
                        record["plan"] = plan
                    if billing_cycle is not None:
                        record["billing_cycle"] = billing_cycle
                    if normalized_multiplier is not None:
                        record["credit_multiplier"] = normalized_multiplier
                auth_store.insert_user_record(record)
            else:
                updates: dict = {"password_hash": hash_password(password)}
                if requested_role is not None:
                    updates["role"] = effective_role
                if max_online is not None and actor_role == ROLE_SUDO:
                    updates["max_online"] = normalized_online
                if max_users is not None and actor_role == ROLE_SUDO:
                    updates["max_users"] = normalized_max_users
                if user_max_online is not None and actor_role == ROLE_SUDO:
                    updates["user_max_online"] = normalized_user_online
                # 计费字段与配额同级：只有 sudo 能改已有账号的套餐与倍率。
                if actor_role == ROLE_SUDO:
                    if plan is not None:
                        updates["plan"] = plan
                    if billing_cycle is not None:
                        updates["billing_cycle"] = billing_cycle
                    if normalized_multiplier is not None:
                        updates["credit_multiplier"] = normalized_multiplier
                auth_store.update_user(username, **updates)
        except Exception:
            _logger.exception("保存账号失败：%s", username)
            return False, "保存账号失败，请稍后重试"

        # 密码或角色变化后立刻作废旧会话，避免旧令牌继续生效。
        try:
            auth_store.revoke_user_sessions(username)
        except Exception:
            _logger.exception("清理账号会话失败：%s", username)

    # 开户额度只在新建时入账；已有账号的加减额度走充值入口，避免误把重置密码变成充值。
    # 入账同样只认 sudo：它等价于直接给账号充值。
    if created and normalized_credits and actor_role == ROLE_SUDO:
        try:
            billing_ledger.grant(
                username,
                normalized_credits,
                reason="开户额度",
                actor=actor,
            )
        except Exception:
            _logger.exception("开户额度入账失败：%s", username)
            return False, "账号已创建，但开户额度入账失败，请在充值入口补录"

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


def set_account_status(actor: str, username: str, status: str) -> tuple[bool, str]:
    """停用/启用账号。停用会立刻撤销其全部会话，下一次请求即失效。"""
    if status not in auth_store.VALID_STATUSES:
        return False, "状态不合法"
    if not isinstance(username, str) or not username:
        return False, "账号不存在"
    actor_role = get_user_role(actor)
    actor_record = auth_store.get_user(actor) or {}
    # 两类人来管账号状态：staff（sudo/admin），以及 Business 母账号管自己的子账号。
    privileged = actor_role == ROLE_SUDO
    delegated = actor_role == ROLE_ADMIN or actor_record.get("plan") == "business"
    if not privileged and not delegated:
        return False, "权限不足"
    if username == BUILTIN_SUDO_USERNAME:
        return False, "不能停用系统管理员账号"
    if username == actor:
        return False, "不能停用自己的账号"

    with _auth_state_lock():
        target = auth_store.get_user(username)
        if target is None:
            return False, "账号不存在"
        if not privileged and target.get("owner") != actor:
            return False, "只能管理自己创建的账号"
        if target.get("status", "active") == status:
            return True, "账号状态未变化"
        try:
            if not auth_store.update_user(username, status=status):
                return False, "账号不存在"
            if status == "suspended":
                revoke_user_sessions(username)
        except Exception:
            _logger.exception("更新账号状态失败：%s", username)
            return False, "保存失败，请稍后重试"
    return True, "账号已停用" if status == "suspended" else "账号已启用"


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


# ─── Redis：会话缓存与在线设备 ─────────────────────────────────────────
#
# 两条原则：
# 1. 真值在数据库。Redis 只用来省掉每请求一次主键查询、以及数在线设备；
# 2. Redis 抖动不能影响登录与鉴权，所有调用都走 redis_backend.execute 的降级包装。

SESSION_CACHE_SECONDS = 60
ONLINE_KEY_PREFIX = "online:"


def _session_cache_key(sid: str) -> str:
    return f"sess:{sid}"


def _online_key(username: str) -> str:
    return f"{ONLINE_KEY_PREFIX}{username}"


def _cached_session_user(sid: str) -> Optional[str]:
    value = redis_backend.execute(
        lambda client: client.get(_session_cache_key(sid)), default=None
    )
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return value or None


def _cache_session(sid: str, username: str, expires_at: float) -> None:
    ttl = int(min(SESSION_CACHE_SECONDS, max(expires_at - time.time(), 1)))
    redis_backend.execute(
        lambda client: client.set(_session_cache_key(sid), username, ex=ttl)
    )


def _drop_session_cache(sid: str) -> None:
    redis_backend.execute(lambda client: client.delete(_session_cache_key(sid)))


def _mark_online(username: str, sid: str, now: float) -> None:
    """在线设备用有序集合记：member=sid，score=最近活跃时间。"""

    def handler(client):
        key = _online_key(username)
        client.zadd(key, {sid: now})
        client.zremrangebyscore(key, 0, now - ONLINE_WINDOW_SECONDS)
        client.expire(key, int(ONLINE_WINDOW_SECONDS * 2))
        return True

    redis_backend.execute(handler)


def _redis_online_count(username: str, now: float) -> Optional[int]:
    """Redis 有数据就返回条数；不可用或为空时返回 None，让调用方查库。"""

    def handler(client):
        key = _online_key(username)
        client.zremrangebyscore(key, 0, now - ONLINE_WINDOW_SECONDS)
        return int(client.zcard(key))

    return redis_backend.execute(handler, default=None)


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
    """token 现在就是不透明 sid；返回用户名，或 None。"""
    sid = token
    if not isinstance(sid, str) or not sid:
        return None
    username = _cached_session_user(sid)

    maybe_known, needs_warm = _known_session(sid)
    if not maybe_known:
        # 位图确认该 sid 从未签发：直接拒绝，不打开数据库。
        return None
    if needs_warm:
        _schedule_session_bloom_warm()

    session = auth_store.get_session(sid)
    now = time.time()
    if not session or session.get("revoked"):
        return None
    if float(session.get("expires_at", 0)) < now:
        return None
    if username and session.get("username") != username:
        return None
    username = session["username"]
    if not _cached_session_user(sid):
        _cache_session(sid, username, float(session.get("expires_at", 0)))
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
    _ensure_auth_store()
    record = auth_store.get_user(username)
    if record is None:
        return False, "账号不存在", None, []
    # 兜底：签发会话不止登录一个入口，状态检查不能只放在 authenticate_user。
    if (record.get("status") or "active") == "suspended":
        return False, "账号已停用，请联系管理员", None, []
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
    expires_at = time.time() + SESSION_TTL_SECONDS
    _cache_session(sid, username, expires_at)
    _mark_online(username, sid, time.time())
    for victim in evicted:
        _drop_session_cache(victim)
    if evicted:
        _logger.warning("账号 %s 在线设备超限，已下线 %d 台最久未活跃设备。", username, len(evicted))
    return True, "登录成功", sid, evicted


def revoke_token_session(token: str) -> bool:
    sid = token
    if not isinstance(sid, str) or not sid:
        return False
    try:
        if not session_bloom().maybe_contains(sid):
            # 位图确认从未签发：不必开写事务。
            return False
    except Exception:
        _logger.exception("查询会话布隆过滤器失败，按未知会话继续处理")
    _drop_session_cache(sid)
    return auth_store.revoke_session(sid)


def revoke_user_sessions(username: str) -> int:
    """撤销该账号全部会话，并同步清掉缓存（缓存 TTL 60 秒，不能等它自然过期）。

    这里必须带 online_window：list_sessions 是仅关键字参数，漏掉它会抛
    TypeError，而调用方大多把它包在 try/except 里 —— 于是「改密码踢下线」
    静默失效。online_window 只影响 online 标记，这里不关心，给窗口值即可。
    """
    for session in auth_store.list_sessions(
        usernames=[username], online_window=ONLINE_WINDOW_SECONDS
    ):
        _drop_session_cache(session["sid"])
    redis_backend.execute(lambda client: client.delete(_online_key(username)))
    return auth_store.revoke_user_sessions(username)


def revoke_other_sessions(username: str, keep_sid: Optional[str]) -> int:
    """撤销该账号除 keep_sid 之外的会话：改密后其他设备下线，当前设备继续用。"""
    removed = 0
    for session in auth_store.list_sessions(
        usernames=[username], online_window=ONLINE_WINDOW_SECONDS
    ):
        sid = session["sid"]
        if keep_sid and sid == keep_sid:
            continue
        _drop_session_cache(sid)
        if auth_store.revoke_session(sid):
            removed += 1
    return removed


def change_password(
    username: str,
    current_password: str,
    new_password: str,
    *,
    keep_sid: Optional[str] = None,
) -> tuple[bool, str, int]:
    """用户自助改密：校验旧密码、写入新摘要，并踢掉其他设备的会话。

    返回 (是否成功, 提示, 被撤销的会话数)。管理员重置密码走 upsert_account，语义是
    「全部端重登」；这里保留当前设备——用户正在用的这台不该因为改密而被踢。
    """
    _ensure_auth_store()
    record = auth_store.get_user(username)
    if not isinstance(record, dict):
        return False, "账号不存在", 0
    if (record.get("status") or "active") == "suspended":
        return False, "账号已停用，请联系管理员", 0
    if not isinstance(new_password, str) or len(new_password) > AUTH_PASSWORD_MAX_LENGTH:
        return False, f"密码长度不能超过 {AUTH_PASSWORD_MAX_LENGTH} 位", 0
    if len(new_password) < PASSWORD_MIN_LENGTH:
        return False, f"密码长度不能小于 {PASSWORD_MIN_LENGTH} 位", 0
    if not verify_password(current_password, record.get("password_hash")):
        return False, "当前密码不正确", 0
    if verify_password(new_password, record.get("password_hash")):
        return False, "新密码不能与当前密码相同", 0

    with _auth_state_lock():
        if not auth_store.update_user(username, password_hash=hash_password(new_password)):
            return False, "保存失败，请稍后重试", 0
    removed = revoke_other_sessions(username, keep_sid)
    # 改密成功顺手解开登录锁定：用户已经证明了自己是谁，不必再等满锁定窗口。
    try:
        from infra import throttle

        throttle.unlock(username)
    except Exception:
        _logger.exception("改密后解除锁定时失败：%s", username)
    return True, "密码已更新，其他设备需重新登录", removed


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
    _drop_session_cache(sid)
    auth_store.revoke_session(sid)
    return True, "已下线该设备"


def hash_client_identity(client_ip: Optional[str]) -> Optional[str]:
    """IP 只保存带密钥的摘要，避免在会话表里落原文。

    IP 取值空间很小，无密钥 SHA-256 可被离线穷举还原；这里用 SECRET_KEY
    作 HMAC 密钥，摘要泄露不再等价于 IP 泄露。
    """
    if not client_ip:
        return None
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        str(client_ip).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]


# ─── 锁定策略（沿用 JSON 存储） ────────────────────────────────────────────


def check_lockout(username: str, client_identity: str = "unknown") -> Optional[str]:
    """账号/来源被锁时返回提示，否则 None。

    实现在 infra/throttle.py：Redis 快路径（锁定标记与计数）+ Postgres 事实源。
    调用点在密码校验之前，被锁的请求不会消耗 PBKDF2 的 CPU。
    """
    try:
        return throttle.is_locked(username, client_identity)
    except Exception:
        _logger.exception("查询登录节流状态失败，按未锁定处理")
        return None


def record_login_attempt(
    username: str,
    success: bool,
    client_identity: str = "unknown",
    *,
    account_exists: Optional[bool] = None,
):
    """记录一次登录结果：失败进节流桶，成功清掉计数。

    不存在的账号**不记录**：否则攻击者可以用任意用户名刷出一堆桶。
    """
    if not isinstance(username, str) or not username or len(username) > AUTH_USERNAME_MAX_LENGTH:
        return
    try:
        if account_exists is None:
            account_exists = auth_store.get_user(username) is not None
        if not account_exists:
            return
        if success:
            throttle.clear(username, client_identity)
            return
        # 两个桶都要记：来源桶给硬上限，账号桶跨来源累计。
        throttle.record_failure(username, client_identity, bucket=throttle.SCOPE_CLIENT)
        throttle.record_failure(username, client_identity, bucket=throttle.SCOPE_ACCOUNT)
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
    _ensure_auth_store()
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
        # 锁定期间对**密码错误**的尝试仍回统一文案，不向猜密码的人泄露账号是否被锁；
        # 但密码正确的本人必须看到锁定提示——否则他会以为密码被改了，只能干等或找管理员。
        if verify_password(password, user_data.get("password_hash")):
            return False, lock_msg
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return False, "用户名或密码错误"

    hashed = user_data.get("password_hash")
    if verify_password(password, hashed):
        # 停用必须在这里拦住：只靠停用时撤销存量会话的话，被停用者用正确密码就能拿回全新会话，
        # 「停用」等于没停。放在密码校验之后是有意的——向猜密码的人泄露账号状态没有必要，
        # 而密码正确的本人才需要知道真相。
        if (user_data.get("status") or "active") == "suspended":
            return False, "账号已停用，请联系管理员"
        record_login_attempt(username, True, client_identity, account_exists=True)
        if password_needs_rehash(hashed):
            try:
                _upgrade_password_hash(username, password, hashed)
            except Exception:
                _logger.exception("Failed to upgrade password hash for %s", username)
        return True, "登录成功"

    record_login_attempt(username, False, client_identity, account_exists=True)
    return False, "用户名或密码错误"
