"""
模块描述：账号与会话的持久化层（云端数据库）。

取代过去的 `infra/auth_store.py`（本地 SQLite）：
- 账号与工作台内容同库，充值与扣费才能和账号状态落在同一个事务里；
- 会话改用不透明 sid，表里直接记撤销状态，不需要 JWT 的 auth_version；
- 账号表预置计费字段（plan / billing_cycle / credits_* / status），阶段二直接填。

对外返回 dict（字段名与旧实现一致，时间戳仍是 epoch 秒），上层 auth.py 与路由不用改形状。
每个公开入口都会先 `ensure_tables()`：缺表就建（生产仍走 alembic），
与旧实现里到处调用 `ensure_schema()` 的容错一致。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from infra.database import Base, now as utcnow, transaction

VALID_ROLES = ("sudo", "admin", "user")
VALID_PLANS = ("metered", "go", "pro", "max", "business")
VALID_BILLING_CYCLES = ("prepaid", "monthly", "yearly")
VALID_STATUSES = ("active", "suspended")

ONLINE_LIMIT_ACTION_KICK = "kick"
ONLINE_LIMIT_ACTION_REJECT = "reject"

# 变更白名单：调用方只能改这些列（旧实现的白名单 + 计费字段）。
MUTABLE_FIELDS = (
    "password_hash",
    "role",
    "owner",
    "max_online",
    "max_users",
    "user_max_online",
    "plan",
    "billing_cycle",
    "credits_balance",
    "credit_quota",
    "credit_multiplier",
    "status",
    "last_grant_at",
    "grant_expire_at",
)


class Account(Base):
    __tablename__ = "accounts"

    username: Mapped[str] = mapped_column(String(200), primary_key=True)
    # uid 是稳定标识：username 可改、custom_id 可改，对外（头像 URL、未来跨表引用）
    # 一律用 uid。32 位十六进制，不可枚举。
    uid: Mapped[str] = mapped_column(String(32), unique=True)
    # custom_id 是用户自选的对外句柄（介绍页/个人资料展示用），可空可改；唯一。
    custom_id: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(400))
    role: Mapped[str] = mapped_column(String(16), default="user")
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    max_online: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_max_online: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 计费：阶段二启用，列先建好，免得再欠一次迁移。
    plan: Mapped[str] = mapped_column(String(16), default="metered")
    billing_cycle: Mapped[str] = mapped_column(String(16), default="prepaid")
    credits_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    credit_quota: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    credit_multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    # 头像字节直接入库（accounts 量级小，省一套对象存储依赖）；version 用于缓存失效。
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_content_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    avatar_version: Mapped[int] = mapped_column(Integer, default=0)
    # 预约中的套餐变更（降级/切回按量）：到 pending_effective_at 由读取路径懒应用。
    pending_plan: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pending_effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_grant_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    grant_expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class AccountSession(Base):
    __tablename__ = "account_sessions"

    sid: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    client: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_account_sessions_online", "username", "revoked", "last_seen_at"),
    )


_READY_URL: Optional[str] = None


def ensure_tables() -> None:
    """建表（缺才建）。同一连接串在本进程只检查一次。"""
    global _READY_URL
    from infra.database import create_tables, database_url, engine_for

    url = database_url()
    if _READY_URL == url:
        return
    create_tables(
        engine_for(url), [Account.__table__, AccountSession.__table__], metadata=Account.metadata
    )
    _READY_URL = url


def _epoch(value: Optional[datetime]) -> Optional[float]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _stamp(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def new_uid() -> str:
    return uuid.uuid4().hex


def _account_dict(row: Account) -> dict[str, Any]:
    # 头像字节不入 dict：它只走 /api/avatars/{uid} 单独取，避免每个账号读取都搬一遍。
    return {
        "username": row.username,
        "uid": row.uid,
        "custom_id": row.custom_id,
        "password_hash": row.password_hash,
        "role": row.role,
        "owner": row.owner,
        "max_online": row.max_online,
        "max_users": row.max_users,
        "user_max_online": row.user_max_online,
        "plan": row.plan,
        "billing_cycle": row.billing_cycle,
        "credits_balance": row.credits_balance,
        "credit_quota": row.credit_quota,
        "credit_multiplier": row.credit_multiplier,
        "status": row.status,
        "avatar_version": row.avatar_version,
        "pending_plan": row.pending_plan,
        "pending_effective_at": _epoch(row.pending_effective_at),
        "last_grant_at": _epoch(row.last_grant_at),
        "grant_expire_at": _epoch(row.grant_expire_at),
        "created_at": _epoch(row.created_at),
        "updated_at": _epoch(row.updated_at),
    }


def _session_dict(row: AccountSession) -> dict[str, Any]:
    return {
        "sid": row.sid,
        "username": row.username,
        "created_at": _epoch(row.created_at),
        "last_seen_at": _epoch(row.last_seen_at),
        "expires_at": _epoch(row.expires_at),
        "client": row.client,
        "user_agent": row.user_agent,
        "ip_hash": row.ip_hash,
        "revoked": 1 if row.revoked else 0,
    }


# ─── accounts ─────────────────────────────────────────────────────────────


def get_user(username: str) -> Optional[dict[str, Any]]:
    ensure_tables()
    with transaction() as session:
        row = session.get(Account, username)
        return _account_dict(row) if row else None


def get_all_users() -> list[dict[str, Any]]:
    ensure_tables()
    with transaction() as session:
        rows = session.scalars(select(Account).order_by(Account.username)).all()
        return [_account_dict(row) for row in rows]


def count_users() -> int:
    ensure_tables()
    with transaction() as session:
        return int(session.scalar(select(func.count()).select_from(Account)) or 0)


def count_owned_users(owner: str) -> int:
    ensure_tables()
    with transaction() as session:
        return int(
            session.scalar(
                select(func.count()).select_from(Account).where(Account.owner == owner)
            )
            or 0
        )


def insert_user_record(record: dict[str, Any]) -> None:
    """按引导/迁移提供的完整记录写入一行；未给的字段走列默认值。"""
    ensure_tables()
    payload = {
        "username": record["username"],
        "uid": record.get("uid") or new_uid(),
        "custom_id": record.get("custom_id"),
        "password_hash": record["password_hash"],
        "role": record.get("role", "user"),
        "owner": record.get("owner"),
        "max_online": record.get("max_online"),
        "max_users": record.get("max_users"),
        "user_max_online": record.get("user_max_online"),
        "plan": record.get("plan", "metered"),
        "billing_cycle": record.get("billing_cycle", "prepaid"),
        "credits_balance": int(record.get("credits_balance", 0)),
        "credit_quota": record.get("credit_quota"),
        "credit_multiplier": record.get("credit_multiplier"),
        "status": record.get("status", "active"),
    }
    with transaction() as session:
        session.add(Account(**payload))


def update_user(username: str, *, now: Optional[float] = None, **fields: Any) -> bool:
    """只更新白名单内的列；调用方保证业务规则（权限、配额）已经校验过。"""
    ensure_tables()
    updates = {k: v for k, v in fields.items() if k in MUTABLE_FIELDS}
    if not updates:
        return False
    updates["updated_at"] = _stamp(now) if now is not None else utcnow()
    with transaction() as session:
        result = session.execute(
            update(Account).where(Account.username == username).values(**updates)
        )
        return bool(result.rowcount)


def delete_user_row(username: str) -> bool:
    ensure_tables()
    with transaction() as session:
        result = session.execute(delete(Account).where(Account.username == username))
        session.execute(
            delete(AccountSession).where(AccountSession.username == username)
        )
        return bool(result.rowcount)


# ─── 个人资料（custom_id / 头像）───────────────────────────────────────────


def set_custom_id(username: str, custom_id: Optional[str]) -> str:
    """写入自选句柄；返回 "ok" 或 "conflict"（撞了别人的句柄）。

    先查后写处理最常见的冲突；先查后写之间被人抢注时由唯一约束兜底，
    同样按 "conflict" 返回（路由层转 409），而不是把 IntegrityError 抛成 500。
    """
    ensure_tables()
    try:
        with transaction() as session:
            if custom_id:
                owner = session.execute(
                    select(Account.username).where(Account.custom_id == custom_id)
                ).first()
                if owner and owner[0] != username:
                    return "conflict"
            session.execute(
                update(Account)
                .where(Account.username == username)
                .values(custom_id=custom_id, updated_at=utcnow())
            )
    except IntegrityError:
        return "conflict"
    return "ok"


def get_avatar(username: str) -> Optional[dict[str, Any]]:
    ensure_tables()
    with transaction() as session:
        row = session.execute(
            select(Account.avatar, Account.avatar_content_type, Account.avatar_version).where(
                Account.username == username
            )
        ).first()
        if not row or row[0] is None:
            return None
        return {"data": row[0], "content_type": row[1], "version": row[2]}


def set_avatar(username: str, data: bytes, content_type: str) -> int:
    ensure_tables()
    with transaction() as session:
        row = session.get(Account, username)
        if not row:
            return 0
        row.avatar = data
        row.avatar_content_type = content_type
        row.avatar_version = (row.avatar_version or 0) + 1
        row.updated_at = utcnow()
        return row.avatar_version


def clear_avatar(username: str) -> int:
    ensure_tables()
    with transaction() as session:
        row = session.get(Account, username)
        if not row:
            return 0
        row.avatar = None
        row.avatar_content_type = None
        row.avatar_version = (row.avatar_version or 0) + 1
        row.updated_at = utcnow()
        return row.avatar_version


def set_pending_plan(
    username: str, target: Optional[str], effective_at: Optional[datetime]
) -> bool:
    """预约/清除套餐变更。清除传 (None, None)。"""
    ensure_tables()
    with transaction() as session:
        result = session.execute(
            update(Account)
            .where(Account.username == username)
            .values(
                pending_plan=target,
                pending_effective_at=effective_at,
                updated_at=utcnow(),
            )
        )
        return bool(result.rowcount)


def apply_pending_plan_if_due(username: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """到点的预约变更在这里落地：plan=pending、清预约。返回（可能的）新 plan。"""
    ensure_tables()
    moment = now or datetime.now(timezone.utc)
    with transaction() as session:
        row = session.execute(
            select(Account.plan, Account.pending_plan, Account.pending_effective_at).where(
                Account.username == username
            )
        ).first()
        if not row or not row[1] or not row[2]:
            return None
        effective = row[2] if row[2].tzinfo else row[2].replace(tzinfo=timezone.utc)
        if moment < effective:
            return None
        values: dict[str, Any] = {
            "plan": row[1],
            "pending_plan": None,
            "pending_effective_at": None,
            "updated_at": utcnow(),
        }
        if row[1] == "metered":
            # 切回按量 = 退出订阅：计费方式一并回到 prepaid（与管理台开按量户的口径一致），
            # 否则 multiplier_for 仍按 monthly/yearly 给订阅折扣。
            values["billing_cycle"] = "prepaid"
        session.execute(
            update(Account).where(Account.username == username).values(**values)
        )
        return row[1]


def get_avatar_by_uid(uid: str) -> Optional[dict[str, Any]]:
    ensure_tables()
    with transaction() as session:
        row = session.execute(
            select(Account.avatar, Account.avatar_content_type, Account.avatar_version).where(
                Account.uid == uid
            )
        ).first()
        if not row or row[0] is None:
            return None
        return {"data": row[0], "content_type": row[1], "version": row[2]}


# ─── sessions ─────────────────────────────────────────────────────────────


def _window_start(window: float, now: float) -> datetime:
    return _stamp(now - window)


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
    """登记一台在线设备；超限时按策略踢掉最旧设备或直接拒绝。

    先给账号行加锁再数在线数：同一账号的并发登录会排队，不会各自读到同一个旧计数。
    """
    ensure_tables()
    current = time.time() if now is None else now
    created = _stamp(current)
    evicted: list[str] = []
    with transaction() as session:
        # 引导阶段账号可能还没落库，有行才加锁。
        session.execute(
            select(Account.username).where(Account.username == username).with_for_update()
        ).first()

        online = session.scalars(
            select(AccountSession.sid)
            .where(
                AccountSession.username == username,
                AccountSession.revoked.is_(False),
                AccountSession.expires_at > created,
                AccountSession.last_seen_at > _window_start(online_window, current),
            )
            .order_by(AccountSession.last_seen_at.asc())
        ).all()

        if max_online is not None and len(online) >= max_online:
            if limit_action == ONLINE_LIMIT_ACTION_REJECT:
                # 直接返回：本事务除了行锁什么都没改，退出时提交即释放锁。
                return (
                    False,
                    f"该账号最多允许 {max_online} 台设备同时在线，请先在其他设备退出。",
                    [],
                )
            evicted = list(online[: len(online) - max_online + 1])
            session.execute(
                update(AccountSession)
                .where(AccountSession.sid.in_(evicted))
                .values(revoked=True)
            )

        session.add(
            AccountSession(
                sid=sid,
                username=username,
                created_at=created,
                last_seen_at=created,
                expires_at=_stamp(current + ttl_seconds),
                client=client,
                user_agent=user_agent,
                ip_hash=ip_hash,
                revoked=False,
            )
        )
    return True, "登录成功", evicted


def get_session(sid: str) -> Optional[dict[str, Any]]:
    if not sid:
        return None
    ensure_tables()
    with transaction() as session:
        row = session.get(AccountSession, sid)
        return _session_dict(row) if row else None


def touch_session(sid: str, *, now: Optional[float] = None) -> None:
    ensure_tables()
    current = time.time() if now is None else now
    with transaction() as session:
        session.execute(
            update(AccountSession)
            .where(AccountSession.sid == sid)
            .values(last_seen_at=_stamp(current))
        )


def revoke_session(sid: str) -> bool:
    ensure_tables()
    with transaction() as session:
        result = session.execute(
            update(AccountSession)
            .where(AccountSession.sid == sid, AccountSession.revoked.is_(False))
            .values(revoked=True)
        )
        return bool(result.rowcount)


def revoke_user_sessions(username: str) -> int:
    ensure_tables()
    with transaction() as session:
        result = session.execute(
            update(AccountSession)
            .where(AccountSession.username == username, AccountSession.revoked.is_(False))
            .values(revoked=True)
        )
        return int(result.rowcount or 0)


def count_online(
    username: str, *, online_window: float, now: Optional[float] = None
) -> int:
    ensure_tables()
    current = time.time() if now is None else now
    with transaction() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(AccountSession)
                .where(
                    AccountSession.username == username,
                    AccountSession.revoked.is_(False),
                    AccountSession.expires_at > _stamp(current),
                    AccountSession.last_seen_at > _window_start(online_window, current),
                )
            )
            or 0
        )


def online_counts(usernames: Iterable[str], *, online_window: float) -> dict[str, int]:
    names = [name for name in usernames]
    if not names:
        return {}
    ensure_tables()
    current = time.time()
    counts = {name: 0 for name in names}
    with transaction() as session:
        rows = session.execute(
            select(AccountSession.username, func.count())
            .where(
                AccountSession.username.in_(names),
                AccountSession.revoked.is_(False),
                AccountSession.expires_at > _stamp(current),
                AccountSession.last_seen_at > _window_start(online_window, current),
            )
            .group_by(AccountSession.username)
        ).all()
        for username, count in rows:
            counts[username] = int(count)
    return counts


def list_sessions(
    *,
    usernames: Optional[Iterable[str]] = None,
    online_window: float,
    online_only: bool = False,
) -> list[dict[str, Any]]:
    ensure_tables()
    current = time.time()
    scope = list(usernames) if usernames is not None else None
    if scope is not None and not scope:
        return []
    query = select(AccountSession).where(
        AccountSession.expires_at > _stamp(current),
        AccountSession.revoked.is_(False),
    )
    if online_only:
        query = query.where(
            AccountSession.last_seen_at > _window_start(online_window, current)
        )
    if scope is not None:
        query = query.where(AccountSession.username.in_(scope))
    query = query.order_by(AccountSession.last_seen_at.desc())
    cutoff = current - online_window
    with transaction() as session:
        rows = session.scalars(query).all()
        return [
            {
                **_session_dict(row),
                "online": bool((_epoch(row.last_seen_at) or 0) > cutoff),
            }
            for row in rows
        ]
