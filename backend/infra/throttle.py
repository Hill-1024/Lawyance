"""
模块描述：登录失败节流——挡密码爆破与登录洪水。

两层，各司其职：
- **Redis 是快路径**：计数用 INCR+EXPIRE（原子、无锁、只为一次网络往返），
  锁定标记用带 TTL 的键，命中即拒、根本不碰数据库与密码哈希。
- **Postgres 是事实源**：锁定状态落表，进程重启、Redis 重启、多 worker 都不丢。

两条桶（与旧实现一致，策略未变）：
- `client`：同一账号 + 同一来源的硬桶，3 次失败 → 锁 2 小时；
- `account`：同账号聚合桶，跨来源累计，从第 6 次起按 5 秒翻倍退避（上限 15 分钟）。

为什么这样能抗洪水：被锁定的请求只花一次 Redis EXISTS；未锁定但正在被爆破的
请求，靠一个 5 秒的否定缓存在 Redis 里挡掉，数据库每 5 秒最多被查一次；
而**密码哈希（PBKDF2 60 万轮）只在真正需要校验时才算**——攻击者拿不到 CPU。
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Optional

from sqlalchemy import BigInteger, Integer, String, case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from infra import redis_backend
from infra.database import Base, transaction

_logger = logging.getLogger("lawver.throttle")

# ─── 策略常量（唯一出处；auth.py 会 re-export 以保持旧调用点可用）─────────

LOCKOUT_FAIL_LIMIT = 3
LOCKOUT_SECONDS = 2 * 3600
LOCKOUT_WINDOW_SECONDS = 15 * 60
ACCOUNT_LOCKOUT_PROGRESSIVE_START = 6
ACCOUNT_LOCKOUT_BASE_SECONDS = 5
ACCOUNT_LOCKOUT_MAX_SECONDS = 15 * 60
ACCOUNT_LOCKOUT_FAIL_CAP = 32
AUTH_USERNAME_MAX_LENGTH = 128
CLIENT_IDENTITY_MAX_LENGTH = 128
# 表里最多留多少条桶：攻击者可以用任意用户名/来源刷键，必须有上限。
LOCKOUT_MAX_RECORDS = 4096

SCOPE_ACCOUNT = "account"
SCOPE_CLIENT = "client"

# 否定缓存：Redis 里记住「这个键刚查过、没被锁」，避免每个请求都查库。
NEGATIVE_CACHE_SECONDS = 5

_KEY_PREFIX = "throttle"


class LoginThrottle(Base):
    """一个节流桶。key 是摘要，绝不落原始用户名或 IP。"""

    __tablename__ = "login_throttle"

    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    fails: Mapped[int] = mapped_column(Integer, default=0)
    # 时间一律 epoch 秒：跨 SQLite/Postgres 语义一致，也不会有 naive/aware 比较问题。
    first_failed_at: Mapped[float] = mapped_column(BigInteger, default=0.0)
    last_failed_at: Mapped[float] = mapped_column(BigInteger, default=0.0, index=True)
    locked_until: Mapped[float] = mapped_column(BigInteger, default=0.0, index=True)


_READY_URL: Optional[str] = None


def ensure_tables() -> None:
    global _READY_URL
    from infra.database import database_url, engine_for

    url = database_url()
    if _READY_URL == url:
        return
    LoginThrottle.__table__.create(engine_for(url), checkfirst=True)
    _READY_URL = url


# ─── 键 ───────────────────────────────────────────────────────────────────


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# 用户名摘要的前 20 个十六进制字符（80 位）做前缀，剩下的位数给来源摘要。
# 这样 client 桶仍然查不出原始用户名，却能按「同一个账号」前缀找齐——
# 否则管理员拿着摘要根本不知道帮谁解锁。
ACCOUNT_PREFIX_CHARS = 20


def account_key(username: str) -> str:
    return digest(f"account\0{str(username)[:AUTH_USERNAME_MAX_LENGTH]}")


def account_prefix(username: str) -> str:
    return account_key(username)[:ACCOUNT_PREFIX_CHARS]


def client_key(username: str, client_identity: str) -> str:
    client_digest = digest(
        f"client\0{str(username)[:AUTH_USERNAME_MAX_LENGTH]}\0"
        f"{str(client_identity or 'unknown')[:CLIENT_IDENTITY_MAX_LENGTH]}"
    )
    return account_prefix(username) + client_digest[: 64 - ACCOUNT_PREFIX_CHARS]


def _redis(scope: str, kind: str, key: str) -> str:
    return f"{_KEY_PREFIX}:{kind}:{scope}:{key}"


def _stamp(seconds: float) -> float:
    return float(seconds)


def _epoch(value: Optional[float]) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ─── Redis 快路径 ─────────────────────────────────────────────────────────


def _redis_locked(scope: str, key: str) -> Optional[float]:
    """返回锁定剩余秒数；None 表示 Redis 里没有锁定标记（不代表没锁，需查库）。"""
    def handler(client):
        ttl = client.ttl(_redis(scope, "lock", key))
        try:
            ttl = int(ttl)
        except (TypeError, ValueError):
            return None
        return ttl if ttl > 0 else None

    return redis_backend.execute(handler, default=None)


def _redis_mark_negative(scope: str, key: str) -> None:
    redis_backend.execute(
        lambda client: client.set(
            _redis(scope, "ok", key), "1", ex=NEGATIVE_CACHE_SECONDS
        )
    )


def _redis_is_negative(scope: str, key: str) -> bool:
    return bool(
        redis_backend.execute(
            lambda client: client.exists(_redis(scope, "ok", key)), default=0
        )
    )


def _redis_lock(scope: str, key: str, seconds: float) -> None:
    if seconds <= 0:
        return
    redis_backend.execute(
        lambda client: client.set(
            _redis(scope, "lock", key), "1", ex=max(int(seconds), 1)
        )
    )
    redis_backend.execute(lambda client: client.delete(_redis(scope, "ok", key)))


def _redis_clear(scope: str, key: str) -> None:
    def handler(client):
        client.delete(
            _redis(scope, "lock", key),
            _redis(scope, "ok", key),
            _redis(scope, "fails", key),
        )
        return True

    redis_backend.execute(handler)


# ─── 策略计算 ─────────────────────────────────────────────────────────────


def lock_seconds_for(bucket: str, fails: int) -> float:
    """桶达到阈值后应该锁多久；**没到阈值一律返回 0**。

    这里必须显式判阈值：少了这一句，第一次输错密码就会锁满 2 小时。
    """
    if bucket == SCOPE_CLIENT:
        return float(LOCKOUT_SECONDS) if fails >= LOCKOUT_FAIL_LIMIT else 0.0
    # 聚合桶：从起始次数开始按 5 秒翻倍，封顶 15 分钟。
    over = fails - ACCOUNT_LOCKOUT_PROGRESSIVE_START
    if over < 0:
        return 0.0
    return float(
        min(ACCOUNT_LOCKOUT_BASE_SECONDS * (2**over), ACCOUNT_LOCKOUT_MAX_SECONDS)
    )


def bucket_threshold(bucket: str) -> int:
    if bucket == SCOPE_CLIENT:
        return LOCKOUT_FAIL_LIMIT
    return ACCOUNT_LOCKOUT_PROGRESSIVE_START + 1


def _prune(session, now: float) -> None:
    """删掉过期到没有意义的桶，并给总量封顶。"""
    session.execute(
        delete(LoginThrottle).where(
            LoginThrottle.locked_until < now - LOCKOUT_WINDOW_SECONDS,
            LoginThrottle.last_failed_at < now - LOCKOUT_WINDOW_SECONDS,
        )
    )
    total = int(session.scalar(select(func.count()).select_from(LoginThrottle)) or 0)
    if total <= LOCKOUT_MAX_RECORDS:
        return
    # 超限时删最老的一批。**两个 scope 都要算**：攻击者既可以用任意来源刷
    # client 桶，也可以用任意用户名刷 account 桶，只清一边等于留了个开口。
    doomed = session.execute(
        select(LoginThrottle.scope, LoginThrottle.key)
        .order_by(LoginThrottle.last_failed_at.asc())
        .limit(total - LOCKOUT_MAX_RECORDS)
    ).all()
    for scope, key in doomed:
        session.execute(
            delete(LoginThrottle).where(
                LoginThrottle.scope == scope, LoginThrottle.key == key
            )
        )


# ─── 对外：查锁、记失败、清桶 ─────────────────────────────────────────────


def is_locked(username: str, client_identity: str = "unknown") -> Optional[str]:
    """返回锁定提示，或 None 表示可以继续校验密码。"""
    if (
        not isinstance(username, str)
        or not username
        or len(username) > AUTH_USERNAME_MAX_LENGTH
    ):
        return None

    pairs = (
        (SCOPE_ACCOUNT, account_key(username)),
        (SCOPE_CLIENT, client_key(username, client_identity)),
    )

    # 1) Redis 快路径：命中锁定标记直接拒，一分钟都不多花。
    redis_available = redis_backend.is_configured()
    if redis_available:
        remaining = 0.0
        for scope, key in pairs:
            ttl = _redis_locked(scope, key)
            if ttl:
                remaining = max(remaining, float(ttl))
        if remaining:
            return _lock_message(remaining)
        # 2) 否定缓存：刚查过且没锁，就不必再查库。
        if all(_redis_is_negative(scope, key) for scope, key in pairs):
            return None

    now = time.time()
    ensure_tables()
    with transaction() as session:
        rows = {
            (row.scope, row.key): _epoch(row.locked_until)
            for row in session.scalars(
                select(LoginThrottle).where(
                    LoginThrottle.key.in_([key for _, key in pairs])
                )
            ).all()
        }
    locked_until = max(
        (rows.get(pair, 0.0) for pair in pairs),
        default=0.0,
    )
    if locked_until > now:
        if redis_available:
            for scope, key in pairs:
                _redis_lock(scope, key, locked_until - now)
        return _lock_message(locked_until - now)

    if redis_available:
        for scope, key in pairs:
            _redis_mark_negative(scope, key)
    return None


def _lock_message(remaining: float) -> str:
    return f"账户已被锁定，请 {int(remaining / 60) + 1} 分钟后再试。"


def _ensure_row(scope: str, key: str, now: float) -> None:
    """保证桶存在。并发下可能有人抢先插入，冲突忽略即可。"""
    try:
        with transaction() as session:
            if session.get(LoginThrottle, (scope, key)) is None:
                session.add(
                    LoginThrottle(
                        scope=scope,
                        key=key,
                        fails=0,
                        first_failed_at=now,
                        last_failed_at=now,
                        locked_until=0.0,
                    )
                )
    except IntegrityError:
        pass  # 另一个请求已经建好了这个桶


def record_failure(
    username: str, client_identity: str = "unknown", *, bucket: str = SCOPE_CLIENT
) -> None:
    """记一次失败并把达到阈值的桶锁上。

    计数必须是**原子自增**：早先的实现是「读出来 +1 再写回」，两个并发请求会各自
    读到同一个旧值，双双写回 → 丢一次计数（跨来源爆破时正好能刷过阈值）。
    这里改成一条带 CASE 的 UPDATE，窗口重置与封顶都在 SQL 里完成，两个引擎语义一致。
    """
    if not isinstance(username, str) or not username:
        return
    now = time.time()
    actual = SCOPE_ACCOUNT if bucket == SCOPE_ACCOUNT else SCOPE_CLIENT
    key = (
        account_key(username)
        if actual == SCOPE_ACCOUNT
        else client_key(username, client_identity)
    )
    cutoff = now - LOCKOUT_WINDOW_SECONDS

    # Redis 计数（可用时）：只用于「这次是否越线」，不承担持久化。
    counted = redis_backend.execute(
        lambda client: _incr(client, actual, key), default=None
    )

    ensure_tables()
    _ensure_row(actual, key, now)

    with transaction() as session:
        increment = case(
            (
                LoginThrottle.fails >= ACCOUNT_LOCKOUT_FAIL_CAP,
                ACCOUNT_LOCKOUT_FAIL_CAP,
            ),
            else_=LoginThrottle.fails + 1,
        )
        session.execute(
            update(LoginThrottle)
            .where(
                LoginThrottle.scope == actual,
                LoginThrottle.key == key,
                # 已锁定的桶不再累加：锁期内失败多少次都是同一次锁定，
                # 让它继续涨只会把 fails 顶到封顶值，失去「阈值」这个信号。
                LoginThrottle.locked_until <= now,
            )
            .values(
                # 超出窗口就从 1 重新数起，否则在旧值上自增。
                fails=case(
                    (LoginThrottle.last_failed_at < cutoff, 1), else_=increment
                ),
                first_failed_at=case(
                    (LoginThrottle.last_failed_at < cutoff, now),
                    else_=LoginThrottle.first_failed_at,
                ),
                last_failed_at=now,
            )
        )
        row = session.get(LoginThrottle, (actual, key))
        if row is None or row.locked_until > now:
            return  # 已经在锁里，不必再累加

        # Redis 有计数时以它为准——它是原子的，能从任何丢更新里自愈。
        fails = max(int(row.fails or 0), int(counted or 0))
        seconds = lock_seconds_for(actual, fails)
        if seconds > 0:
            session.execute(
                update(LoginThrottle)
                .where(LoginThrottle.scope == actual, LoginThrottle.key == key)
                .values(locked_until=now + seconds)
            )
            _redis_lock(actual, key, seconds)
        _prune(session, now)


def _incr(client, scope: str, key: str) -> int:
    redis_key = _redis(scope, "fails", key)
    value = client.incr(redis_key)
    if value == 1:
        client.expire(redis_key, LOCKOUT_WINDOW_SECONDS)
    return int(value)


def clear(username: str, client_identity: str = "unknown") -> None:
    """登录成功后清掉这个来源与账号的失败计数（锁定中的桶不动）。"""
    if not isinstance(username, str) or not username:
        return
    now = time.time()
    pairs = (
        (SCOPE_ACCOUNT, account_key(username)),
        (SCOPE_CLIENT, client_key(username, client_identity)),
    )
    for scope, key in pairs:
        _redis_clear(scope, key)
    ensure_tables()
    with transaction() as session:
        session.execute(
            delete(LoginThrottle).where(
                LoginThrottle.key.in_([key for _, key in pairs]),
                LoginThrottle.locked_until <= now,
            )
        )


def snapshot(limit: int = 200) -> list[dict[str, Any]]:
    """管理面板用：当前还在生效的桶（键是摘要，仍然不外泄原文）。"""
    ensure_tables()
    now = time.time()
    with transaction() as session:
        rows = session.scalars(
            select(LoginThrottle)
            .where(LoginThrottle.last_failed_at >= now - LOCKOUT_WINDOW_SECONDS)
            .order_by(LoginThrottle.last_failed_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "scope": row.scope,
                "key": row.key[:12],
                "fails": row.fails,
                "locked_seconds": max(int(_epoch(row.locked_until) - now), 0),
                "last_failed_at": _epoch(row.last_failed_at),
            }
            for row in rows
        ]


def locked_seconds(username: str, client_identity: str = "unknown") -> int:
    """该账号当前还被锁多少秒（取两个桶里更长的那个）。"""
    if not isinstance(username, str) or not username:
        return 0
    now = time.time()
    pairs = (
        (SCOPE_ACCOUNT, account_key(username)),
        (SCOPE_CLIENT, client_key(username, client_identity)),
    )
    ensure_tables()
    with transaction() as session:
        rows = session.scalars(
            select(LoginThrottle).where(LoginThrottle.key.in_([key for _, key in pairs]))
        ).all()
    remaining = max((_epoch(row.locked_until) - now for row in rows), default=0.0)
    return max(int(remaining), 0)


def unlock(username: str) -> int:
    """清掉这个账号的节流状态（账号桶 + 它名下的全部来源桶）。

    给管理员用：用户自己连着输错密码被锁两小时，线上不该只能干等。
    返回清掉的桶数；键是摘要，所以按前缀找来源桶。
    """
    if not isinstance(username, str) or not username:
        return 0
    prefix = account_prefix(username)
    ensure_tables()
    with transaction() as session:
        rows = session.scalars(
            select(LoginThrottle).where(
                (LoginThrottle.key == account_key(username))
                | (LoginThrottle.key.startswith(prefix))
            )
        ).all()
        pairs = [(row.scope, row.key) for row in rows]
        for scope, key in pairs:
            session.execute(
                delete(LoginThrottle).where(
                    LoginThrottle.scope == scope, LoginThrottle.key == key
                )
            )
    # Redis 里的计数与锁定标记也要一起清，否则快路径仍然拦人。
    for scope, key in pairs:
        _redis_clear(scope, key)
    return len(pairs)


def locked_map(usernames) -> dict[str, int]:
    """{用户名: 剩余锁定秒数}，把该用户名名下的来源桶也算进去。

    账号列表要显示「谁正被锁着」，而锁定通常发生在某个来源桶上，
    所以按前缀把来源桶归回账号。表有上限，整表读进内存聚合是可接受的。
    """
    names = [name for name in usernames if isinstance(name, str) and name]
    if not names:
        return {}
    exact = {account_key(name): name for name in names}
    prefixes = {account_prefix(name): name for name in names}
    now = time.time()
    ensure_tables()
    with transaction() as session:
        rows = session.scalars(select(LoginThrottle)).all()
    out = {name: 0 for name in names}
    for row in rows:
        owner = exact.get(row.key) or prefixes.get(row.key[:ACCOUNT_PREFIX_CHARS])
        if owner is None:
            continue
        remaining = int(_epoch(row.locked_until) - now)
        if remaining > out[owner]:
            out[owner] = remaining
    return out
