"""
模块描述：账号与会话的 SQLite 存储层，替代 account.json，承载角色、配额与在线设备状态。

调用方（auth.py）负责密码哈希与权限判断，这里只做持久化：用户表保存摘要与权限参数，
会话表记录每次登录产生的一台在线设备，用于「同一账号在线机器数量」限制与踢下线。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Iterable, Optional

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600

VALID_ROLES = ("sudo", "admin", "user")

# 会话在线判定与用户/配额上限的兜底值，auth.py 会用环境变量覆盖后传入。
DEFAULT_ONLINE_WINDOW_SECONDS = 15 * 60
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 3600
ONLINE_LIMIT_ACTION_KICK = "kick"
ONLINE_LIMIT_ACTION_REJECT = "reject"

_READY_PATH: Optional[str] = None
_DB_READY_LOCK = threading.Lock()
_WRITE_LOCK = threading.RLock()


def db_path() -> str:
    """账号库固定放在数据目录（默认 <cwd>/data）下，与 secrets/settings 等同级。"""
    data_dir = os.environ.get("LAWVER_DATA_DIR") or os.path.join(os.getcwd(), "data")
    return os.path.join(data_dir, "auth.sqlite3")

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS users (
        username        TEXT PRIMARY KEY,
        password_hash   TEXT NOT NULL,
        role            TEXT NOT NULL CHECK(role IN ('sudo', 'admin', 'user')),
        auth_version    INTEGER NOT NULL DEFAULT 0,
        owner           TEXT,
        max_online      INTEGER,
        max_users       INTEGER,
        user_max_online INTEGER,
        created_at      REAL NOT NULL,
        updated_at      REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        sid          TEXT PRIMARY KEY,
        username     TEXT NOT NULL,
        created_at   REAL NOT NULL,
        last_seen_at REAL NOT NULL,
        expires_at   REAL NOT NULL,
        client       TEXT,
        user_agent   TEXT,
        ip_hash      TEXT,
        revoked      INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_owner ON users(owner)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions(username)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_seen ON sessions(last_seen_at)",
)


def _db_paths() -> tuple[str, ...]:
    path = db_path()
    return (path, f"{path}-wal", f"{path}-shm")


def _harden_storage(*, create_database: bool = False) -> None:
    path = db_path()
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, mode=PRIVATE_DIR_MODE, exist_ok=True)
    try:
        os.chmod(parent, PRIVATE_DIR_MODE)
    except OSError:
        pass
    if create_database:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, PRIVATE_FILE_MODE)
        try:
            os.fchmod(fd, PRIVATE_FILE_MODE)
        finally:
            os.close(fd)
    for candidate in _db_paths():
        try:
            os.chmod(candidate, PRIVATE_FILE_MODE)
        except FileNotFoundError:
            continue
        except OSError:
            continue


def harden_storage() -> None:
    """对外暴露的加固入口，供启动时统一收紧目录与数据库权限。"""
    _harden_storage()


def ensure_schema() -> None:
    """创建数据库、表与索引；同一路径进程内只执行一次。"""
    global _READY_PATH
    path = db_path()
    if _READY_PATH == path:
        return
    with _DB_READY_LOCK:
        if _READY_PATH == path:
            return
        with _WRITE_LOCK:
            _harden_storage(create_database=True)
            with closing(_connect()) as conn:
                for statement in _SCHEMA:
                    conn.execute(statement)
                conn.commit()
            _harden_storage()
        _READY_PATH = path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _harden_storage()
    return conn


def _now(now: Optional[float] = None) -> float:
    return time.time() if now is None else now


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


# ─── users ────────────────────────────────────────────────────────────────


def get_user(username: str) -> Optional[dict[str, Any]]:
    ensure_schema()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _row_to_dict(row)


def get_all_users() -> list[dict[str, Any]]:
    ensure_schema()
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
    return [dict(row) for row in rows]


def count_users() -> int:
    ensure_schema()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"]) if row else 0


def count_owned_users(owner: str) -> int:
    ensure_schema()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users WHERE owner = ?", (owner,)).fetchone()
    return int(row["n"]) if row else 0


def insert_user_record(record: dict[str, Any]) -> None:
    """按迁移/引导提供的完整记录写入一行，不做任何字段默认。"""
    ensure_schema()
    now = _now()
    with _WRITE_LOCK, closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO users
                (username, password_hash, role, auth_version, owner,
                 max_online, max_users, user_max_online, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["username"],
                record["password_hash"],
                record["role"],
                int(record.get("auth_version", 0)),
                record.get("owner"),
                record.get("max_online"),
                record.get("max_users"),
                record.get("user_max_online"),
                float(record.get("created_at", now)),
                float(record.get("updated_at", now)),
            ),
        )
        conn.commit()


def update_user(username: str, *, now: Optional[float] = None, **fields: Any) -> bool:
    """更新允许的列；调用方保证字段名来自白名单。"""
    allowed = {
        "password_hash",
        "role",
        "auth_version",
        "owner",
        "max_online",
        "max_users",
        "user_max_online",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    ensure_schema()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values())
    values.append(_now(now))
    values.append(username)
    with _WRITE_LOCK, closing(_connect()) as conn:
        cursor = conn.execute(
            f"UPDATE users SET {assignments}, updated_at = ? WHERE username = ?",
            values,
        )
        conn.commit()
    return cursor.rowcount > 0


def delete_user_row(username: str) -> bool:
    ensure_schema()
    with _WRITE_LOCK, closing(_connect()) as conn:
        cursor = conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
    return cursor.rowcount > 0


# ─── sessions ─────────────────────────────────────────────────────────────


def _purge_expired(conn: sqlite3.Connection, now: float) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))


def _online_sids(conn: sqlite3.Connection, username: str, now: float, window: float) -> list[str]:
    rows = conn.execute(
        """
        SELECT sid FROM sessions
        WHERE username = ? AND revoked = 0 AND expires_at > ? AND last_seen_at > ?
        ORDER BY last_seen_at ASC
        """,
        (username, now, now - window),
    ).fetchall()
    return [row["sid"] for row in rows]


def reserve_session(
    *,
    sid: str,
    username: str,
    max_online: Optional[int],
    limit_action: str,
    ttl_seconds: float,
    online_window: float,
    client: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip_hash: Optional[str] = None,
    now: Optional[float] = None,
) -> tuple[bool, str, list[str]]:
    """原子地登记一台在线设备；超出上限时按策略踢掉最旧设备或直接拒绝。"""
    ensure_schema()
    current = _now(now)
    evicted: list[str] = []
    with _WRITE_LOCK, closing(_connect()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            _purge_expired(conn, current)
            online = _online_sids(conn, username, current, online_window)

            if max_online is not None and len(online) >= max_online:
                if limit_action == ONLINE_LIMIT_ACTION_REJECT:
                    conn.rollback()
                    return (
                        False,
                        f"该账号最多允许 {max_online} 台设备同时在线，请先在其他设备退出。",
                        [],
                    )
                overflow = len(online) - max_online + 1
                evicted = online[:overflow]
                for victim in evicted:
                    conn.execute("UPDATE sessions SET revoked = 1 WHERE sid = ?", (victim,))

            conn.execute(
                """
                INSERT INTO sessions
                    (sid, username, created_at, last_seen_at, expires_at, client, user_agent, ip_hash, revoked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    sid,
                    username,
                    current,
                    current,
                    current + ttl_seconds,
                    client,
                    user_agent,
                    ip_hash,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return True, "登录成功", evicted


def get_session(sid: str) -> Optional[dict[str, Any]]:
    if not sid:
        return None
    ensure_schema()
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
    return _row_to_dict(row)


def touch_session(sid: str, *, now: Optional[float] = None) -> None:
    ensure_schema()
    with _WRITE_LOCK, closing(_connect()) as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE sid = ?", (_now(now), sid))
        conn.commit()


def revoke_session(sid: str) -> bool:
    ensure_schema()
    with _WRITE_LOCK, closing(_connect()) as conn:
        cursor = conn.execute("UPDATE sessions SET revoked = 1 WHERE sid = ?", (sid,))
        conn.commit()
    return cursor.rowcount > 0


def revoke_user_sessions(username: str) -> int:
    ensure_schema()
    with _WRITE_LOCK, closing(_connect()) as conn:
        cursor = conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE username = ? AND revoked = 0",
            (username,),
        )
        conn.commit()
    return cursor.rowcount


def count_online(username: str, *, online_window: float, now: Optional[float] = None) -> int:
    ensure_schema()
    current = _now(now)
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM sessions
            WHERE username = ? AND revoked = 0 AND expires_at > ? AND last_seen_at > ?
            """,
            (username, current, current - online_window),
        ).fetchone()
    return int(row["n"]) if row else 0


def online_counts(usernames: Iterable[str], *, online_window: float) -> dict[str, int]:
    names = [name for name in usernames]
    if not names:
        return {}
    ensure_schema()
    current = time.time()
    counts: dict[str, int] = {name: 0 for name in names}
    with closing(_connect()) as conn:
        # 用户名数量来自调用方过滤后的账号列表，用占位符批量查询避免拼接。
        for chunk_start in range(0, len(names), 500):
            chunk = names[chunk_start:chunk_start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT username, COUNT(*) AS n FROM sessions
                WHERE username IN ({placeholders})
                  AND revoked = 0 AND expires_at > ? AND last_seen_at > ?
                GROUP BY username
                """,
                (*chunk, current, current - online_window),
            ).fetchall()
            for row in rows:
                counts[row["username"]] = int(row["n"])
    return counts


def list_sessions(
    *,
    usernames: Optional[Iterable[str]] = None,
    online_window: float,
    online_only: bool = False,
) -> list[dict[str, Any]]:
    ensure_schema()
    current = time.time()
    clauses = ["expires_at > ?", "revoked = 0"]
    params: list[Any] = [current]
    if online_only:
        clauses.append("last_seen_at > ?")
        params.append(current - online_window)
    scope = list(usernames) if usernames is not None else None
    if scope is not None:
        if not scope:
            return []
        placeholders = ", ".join("?" for _ in scope)
        clauses.append(f"username IN ({placeholders})")
        params.extend(scope)
    query = f"SELECT * FROM sessions WHERE {' AND '.join(clauses)} ORDER BY last_seen_at DESC"
    with closing(_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    cutoff = current - online_window
    return [
        {**dict(row), "online": bool(row["last_seen_at"] > cutoff)}
        for row in rows
    ]
