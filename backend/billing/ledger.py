"""
模块描述：credits 的记账与结算。

三条不变量：
1. **账本只追加**，余额是物化的。任何余额变动都同时写一条账本行；
   对账入口 `reconcile()` 能按账本重算余额。
2. **余额变动与账本写入在同一个事务里**，所以账号必须与账本同库。
3. **计量失败不影响主流程**：`settle()` 出错只记日志，不让一次已经完成的
   模型调用因为统计问题而失败。

拦截（余额不足则拒绝）是调用方的职责，见 `can_spend()`；这里不做拒绝。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, update

from billing import pricing
from billing.models import CreditLedger, TopUp, UsageDaily
from billing.metering import TurnUsage
from infra.account_store import Account
from infra.database import new_id, transaction

_logger = logging.getLogger("lawver.billing")

# 永远不受余额限制的角色：运维自己的账号被计费挡住会让故障排查变得很荒谬。
EXEMPT_ROLES = ("sudo",)

# 计费拦截开关。默认关闭：**先只记账不拦截**，用真实用量核对一轮数字，
# 确认计价口径无误后再打开。关着的时候「账号不存在/已停用」仍然照拦。
ENFORCE_ENV = "LAWVER_BILLING_ENFORCE"


def enforcement_enabled() -> bool:
    return os.getenv(ENFORCE_ENV, "0").strip() == "1"


def ensure_tables() -> None:
    """建表（缺才建）。生产走 alembic，这里保证冷启动与测试不会因为少表而 500。"""
    from infra.database import database_url, engine_for

    engine = engine_for(database_url())
    for model in (CreditLedger, UsageDaily, TopUp):
        model.__table__.create(engine, checkfirst=True)


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ─── 读取 ─────────────────────────────────────────────────────────────────


def balance_micro(session, username: str) -> int:
    value = session.scalar(
        select(Account.credits_balance).where(Account.username == username)
    )
    return int(value or 0)


def balance(username: str) -> int:
    ensure_tables()
    with transaction() as session:
        return balance_micro(session, username)


def is_exempt(username: str) -> bool:
    """运维账号不受余额限制。"""
    ensure_tables()
    with transaction() as session:
        role = session.scalar(select(Account.role).where(Account.username == username))
        return role in EXEMPT_ROLES


def can_spend(username: str) -> tuple[bool, str]:
    """能不能开始一件要花钱的事。返回 (是否允许, 拒绝原因)。

    账号存在性与停用状态永远生效；余额这一条只在 `LAWVER_BILLING_ENFORCE=1`
    时才拦——上线初期先记账、后拦截，否则所有余额为 0 的既有账号会当场失能。
    """
    ensure_tables()
    enforcing = enforcement_enabled()
    with transaction() as session:
        role = session.scalar(select(Account.role).where(Account.username == username))
        if role is None:
            # 记账模式下账号查询失败不该变成新的失败点：鉴权层已经保证账号存在。
            return (False, "账号不存在") if enforcing else (True, "")
        if role in EXEMPT_ROLES:
            return True, ""
        if not enforcing:
            return True, ""
        status = session.scalar(select(Account.status).where(Account.username == username))
        if status == "suspended":
            return False, "账号已停用，请联系管理员"
        if balance_micro(session, username) <= 0:
            return False, "credits 不足，请联系客服充值"
        return True, ""


def recent_ledger(username: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_tables()
    with transaction() as session:
        rows = session.scalars(
            select(CreditLedger)
            .where(CreditLedger.username == username)
            .order_by(CreditLedger.created_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": row.id,
                "delta": pricing.as_credits(row.delta),
                "kind": row.kind,
                "reason": row.reason,
                "ref_id": row.ref_id,
                "meta": row.meta or {},
                "actor": row.actor,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]


def usage_rows(username: str, *, days: int = 30) -> list[dict[str, Any]]:
    ensure_tables()
    with transaction() as session:
        rows = session.scalars(
            select(UsageDaily)
            .where(UsageDaily.username == username)
            .order_by(UsageDaily.day.desc())
            .limit(days)
        ).all()
        return [_usage_dict(row) for row in rows]


def usage_for_many(usernames: Iterable[str], *, days: int = 30) -> dict[str, list[dict[str, Any]]]:
    names = list(usernames)
    if not names:
        return {}
    ensure_tables()
    # days 是硬过滤而不是「取回全部再让调用方截断」：账号多起来以后，
    # 把全量日表读进内存只为显示最近 30 行是不可接受的。
    since = _today() - timedelta(days=max(int(days), 1))
    with transaction() as session:
        rows = session.scalars(
            select(UsageDaily)
            .where(UsageDaily.username.in_(names), UsageDaily.day >= since)
            .order_by(UsageDaily.day.desc())
        ).all()
        grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
        for row in rows:
            grouped.setdefault(row.username, []).append(_usage_dict(row))
        return grouped


def _usage_dict(row: UsageDaily) -> dict[str, Any]:
    return {
        "day": row.day.isoformat(),
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "tool_calls": row.tool_calls,
        "documents": row.documents,
        "turns": row.turns,
        "credits": pricing.as_credits(row.credits_spent),
    }


# ─── 写入 ─────────────────────────────────────────────────────────────────


def _write_ledger(
    session,
    *,
    username: str,
    delta: int,
    kind: str,
    reason: str = "",
    ref_id: str | None = None,
    meta: dict | None = None,
    actor: str | None = None,
) -> None:
    session.add(
        CreditLedger(
            id=new_id(),
            username=username,
            delta=delta,
            kind=kind,
            reason=reason[:300],
            ref_id=ref_id,
            meta=meta or {},
            actor=actor,
        )
    )
    session.execute(
        update(Account)
        .where(Account.username == username)
        .values(credits_balance=Account.credits_balance + delta)
    )


def _bump_daily(session, turn: TurnUsage, spent_micro: int) -> None:
    day = _today()
    row = session.scalar(
        select(UsageDaily).where(
            UsageDaily.username == turn.username, UsageDaily.day == day
        )
    )
    if row is None:
        session.add(
            UsageDaily(
                id=new_id(),
                username=turn.username,
                day=day,
                prompt_tokens=turn.prompt_tokens,
                completion_tokens=turn.completion_tokens,
                tool_calls=turn.tool_calls,
                documents=turn.documents,
                document_chars=turn.document_chars,
                turns=1,
                credits_spent=spent_micro,
            )
        )
        return
    row.prompt_tokens += turn.prompt_tokens
    row.completion_tokens += turn.completion_tokens
    row.tool_calls += turn.tool_calls
    row.documents += turn.documents
    row.document_chars += turn.document_chars
    row.turns += 1
    row.credits_spent += spent_micro
    row.updated_at = datetime.now(timezone.utc)


def settle(turn: TurnUsage | None, *, actor: str | None = None) -> dict[str, Any]:
    """把一轮用量落账：写账本 + 累加当日用量 + 扣余额。返回结算摘要。

    永不抛异常——计量失败不能反过来让用户的任务失败。
    """
    if turn is None or turn.is_empty:
        return {}
    try:
        ensure_tables()
        spent = turn.charged_micro
        with transaction() as session:
            _write_ledger(
                session,
                username=turn.username,
                delta=-spent,
                kind="charge",
                reason=turn.reason or "任务用量",
                ref_id=turn.ref_id,
                meta={
                    "prompt_tokens": turn.prompt_tokens,
                    "completion_tokens": turn.completion_tokens,
                    "tool_calls": turn.tool_calls,
                    "documents": turn.documents,
                    "document_chars": turn.document_chars,
                    "model_calls": turn.model_calls,
                    "multiplier": turn.multiplier,
                    "base_credits": round(turn.base_credits, 4),
                    "calls": turn.calls[:64],
                },
                actor=actor,
            )
            _bump_daily(session, turn, spent)
        return turn.summary()
    except Exception:
        _logger.exception("结算用量失败：%s", turn.username)
        return {}


def grant(
    username: str,
    amount_credits: float,
    *,
    kind: str = "grant",
    reason: str = "",
    actor: str | None = None,
    ref_id: str | None = None,
) -> int:
    """充值/赠送/调整。返回本次入账的 micro-credit。"""
    ensure_tables()
    delta = pricing.credits(amount_credits)
    if delta == 0:
        return 0
    with transaction() as session:
        _write_ledger(
            session,
            username=username,
            delta=delta,
            kind=kind,
            reason=reason,
            ref_id=ref_id,
            actor=actor,
        )
    return delta


def record_topup(
    username: str,
    *,
    amount_yuan: int,
    credits_amount: float,
    note: str = "",
    actor: str | None = None,
) -> dict[str, Any]:
    """登记一笔充值单据并立即入账（客服人工收款场景）。"""
    ensure_tables()
    delta = pricing.credits(credits_amount)
    with transaction() as session:
        topup = TopUp(
            id=new_id(),
            username=username,
            amount_yuan=int(amount_yuan),
            credits=delta,
            note=note,
            actor=actor,
        )
        session.add(topup)
        _write_ledger(
            session,
            username=username,
            delta=delta,
            kind="grant",
            reason=note or f"充值 {amount_yuan} 元",
            ref_id=topup.id,
            actor=actor,
        )
    return {"id": topup.id, "credits": pricing.as_credits(delta)}


def transfer_to_child(
    parent: str, child: str, amount_credits: float, *, actor: str | None = None
) -> tuple[bool, str]:
    """母账号把池子里的 credits 分配给子账号（Business 预算分配）。"""
    ensure_tables()
    delta = pricing.credits(amount_credits)
    if delta <= 0:
        return False, "分配额度必须大于 0"
    with transaction() as session:
        if balance_micro(session, parent) < delta:
            return False, "母账号余额不足"
        _write_ledger(
            session,
            username=parent,
            delta=-delta,
            kind="allocation_out",
            reason=f"分配给子账号 {child}",
            ref_id=child,
            actor=actor,
        )
        _write_ledger(
            session,
            username=child,
            delta=delta,
            kind="allocation_in",
            reason=f"来自母账号 {parent}",
            ref_id=parent,
            actor=actor,
        )
    return True, "分配成功"


def reconcile(username: str) -> dict[str, Any]:
    """按账本重算余额并写回，用于对账。返回 (账本合计, 写入前余额)。"""
    ensure_tables()
    with transaction() as session:
        total = int(
            session.scalar(
                select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
                    CreditLedger.username == username
                )
            )
            or 0
        )
        current = balance_micro(session, username)
        session.execute(
            update(Account)
            .where(Account.username == username)
            .values(credits_balance=total)
        )
    return {"ledger_total": pricing.as_credits(total), "previous": pricing.as_credits(current)}
