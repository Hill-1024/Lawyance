"""
模块描述：计费相关表的模型——credits 账本、按天用量汇总、充值单据。

都挂在 infra.database 的同一个 Base 上，与账号、工作台内容同库：
「扣费 + 记账 + 改余额」必须落在同一个事务里，跨库就没有原子性可言。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infra.database import Base, new_id, now as utcnow


class CreditLedger(Base):
    """只追加的账本。余额是物化的，账本才是审计真值。"""

    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(200), index=True)
    # micro-credit；正数是充值/分配，负数是消耗。
    delta: Mapped[int] = mapped_column(BigInteger)
    # charge / grant / allocation_in / allocation_out / refund / adjust
    kind: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    # 关联对象：run id / 子账号 / 充值单号等。
    ref_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # 明细：模型、token、工具次数、单价与倍率快照——对账时按当时的价格重算。
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    __table_args__ = (Index("ix_credit_ledger_owner_time", "username", "created_at"),)


class UsageDaily(Base):
    """按天汇总：管理面板与 Business 监控只查这一张表。"""

    __tablename__ = "usage_daily"

    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(200), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    documents: Mapped[int] = mapped_column(Integer, default=0)
    document_chars: Mapped[int] = mapped_column(BigInteger, default=0)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    # 实际扣除的 micro-credit（已乘倍率）。
    credits_spent: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (Index("ix_usage_daily_owner_day", "username", "day", unique=True),)


class TopUp(Base):
    """充值单据：管理员/客服收款后登记，审核通过才进账本。"""

    __tablename__ = "credit_topups"

    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(200), index=True)
    amount_yuan: Mapped[int] = mapped_column(Integer)
    credits: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Announcement(Base):
    """开屏公告：按套餐受众与生效时间窗口下发给账号。

    audience 为空列表表示对全部账号可见；starts_at / ends_at 为空表示不设边界。
    下发给谁由读取端过滤，管理员列表则返回全部（含未启用与已过期）。
    """

    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    # info / warning / danger
    level: Mapped[str] = mapped_column(String(16), default="info")
    # 套餐 id 列表；空 = 所有人。
    audience: Mapped[list] = mapped_column(JSON, default=list)
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
