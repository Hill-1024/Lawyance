"""
模块描述：credits 与套餐的 API——用户查自己的余额、用量与自助用量控制台，管理员充值，Business 母账号分配预算。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from auth import get_user_record
from billing import ledger, pricing
from infra import account_store
from services.auth_dependencies import get_current_user, require_staff


router = APIRouter()


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grant(Body):
    """管理员给账号加/减 credits。负数即扣减，必须写原因。"""

    credits: float = Field(description="正数入账，负数扣减")
    reason: str = Field(default="", max_length=300)


class TopUp(Body):
    """客服人工收款后的充值登记：填元数，按当前比价折算 credits。"""

    amount_yuan: int = Field(gt=0, le=1_000_000)
    note: str = Field(default="", max_length=300)


@router.get("/api/plans")
def plans():
    """套餐目录：定价页是公开页面，这里不含任何账号信息。"""
    return {
        "credits_per_yuan": pricing.CREDITS_PER_YUAN,
        "plans": pricing.plan_catalog(),
        "note": "支付尚未开放；开通与充值请联系客服。",
    }


@router.get("/api/credits")
def my_credits(user: str = Depends(get_current_user)):
    """当前账号的额度总览：余额、计费倍率、最近流水与近期用量。"""
    record = get_user_record(user) or {}
    return {
        "username": user,
        "plan": record.get("plan", "metered"),
        "billing_cycle": record.get("billing_cycle", "prepaid"),
        "credits": pricing.as_credits(record.get("credits_balance", 0) or 0),
        "multiplier": pricing.multiplier_for(
            record.get("plan", "metered"),
            record.get("billing_cycle", "prepaid"),
            record.get("credit_multiplier"),
        ),
        "credit_quota": (
            pricing.as_credits(record["credit_quota"])
            if record.get("credit_quota") is not None
            else None
        ),
        "exempt": user in ("admin",) or record.get("role") == "sudo",
        "ledger": ledger.recent_ledger(user, limit=30),
        "usage": ledger.usage_rows(user, days=30),
    }


@router.get("/api/usage/summary")
def my_usage_summary(
    days: int = Query(default=30, ge=1, le=90),
    user: str = Depends(get_current_user),
):
    """自助用量控制台：窗口内按天序列 + 合计，供折线图与数字卡消费。

    缺数据的日期补零，前端拿到的序列天然连续，不用自己补；窗口上限 90 天。
    """
    record = get_user_record(user) or {}
    rows = ledger.usage_rows(user, days=days)
    by_day = {row["day"]: row for row in rows}
    # 以 UTC 日期对齐写入端（ledger._today 同源）；序列升序、缺天补零。
    today = datetime.now(timezone.utc).date()
    series = []
    totals = {"tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "tool_calls": 0, "documents": 0, "turns": 0, "credits": 0.0}
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        row = by_day.get(day)
        if row:
            tokens = (row.get("prompt_tokens") or 0) + (row.get("completion_tokens") or 0)
            entry = {
                "day": day,
                "tokens": tokens,
                "prompt_tokens": row.get("prompt_tokens") or 0,
                "completion_tokens": row.get("completion_tokens") or 0,
                "tool_calls": row.get("tool_calls") or 0,
                "documents": row.get("documents") or 0,
                "turns": row.get("turns") or 0,
                "credits": row.get("credits") or 0,
            }
        else:
            entry = {
                "day": day,
                "tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "tool_calls": 0,
                "documents": 0,
                "turns": 0,
                "credits": 0,
            }
        totals["tokens"] += entry["tokens"]
        totals["prompt_tokens"] += entry["prompt_tokens"]
        totals["completion_tokens"] += entry["completion_tokens"]
        totals["tool_calls"] += entry["tool_calls"]
        totals["documents"] += entry["documents"]
        totals["turns"] += entry["turns"]
        totals["credits"] += entry["credits"]
        series.append(entry)
    return {
        "days": days,
        "plan": record.get("plan", "metered"),
        "balance": pricing.as_credits(record.get("credits_balance", 0) or 0),
        "quota": (
            pricing.as_credits(record["credit_quota"])
            if record.get("credit_quota") is not None
            else None
        ),
        "totals": totals,
        "series": series,
    }


def _require_visible_target(actor: str, target: str) -> dict:
    """管理员只能动自己名下的账号；sudo 不限。"""
    record = get_user_record(target)
    if not record:
        raise HTTPException(404, "账号不存在")
    actor_record = get_user_record(actor) or {}
    if actor_record.get("role") == "sudo":
        return record
    if record.get("owner") != actor:
        raise HTTPException(403, "只能管理自己创建的账号")
    return record


@router.post("/api/admin/accounts/{username}/credits")
def grant_credits(
    username: str, body: Grant, actor: str = Depends(require_staff)
):
    """给账号加/减 credits，并留下带原因的账本记录。"""
    _require_visible_target(actor, username)
    if body.credits == 0:
        raise HTTPException(422, "额度不能为 0")
    if body.credits < 0 and not body.reason.strip():
        raise HTTPException(422, "扣减 credits 必须写明原因")
    delta = ledger.grant(
        username,
        body.credits,
        kind="adjust" if body.credits < 0 else "grant",
        reason=body.reason or "管理员充值",
        actor=actor,
    )
    return {
        "status": "success",
        "username": username,
        "credited": pricing.as_credits(delta),
        "balance": pricing.as_credits(ledger.balance(username)),
    }


@router.post("/api/admin/accounts/{username}/topups")
def top_up(username: str, body: TopUp, actor: str = Depends(require_staff)):
    """按元数登记充值：客服收到款后调用，金额与 credits 一起落单据。"""
    _require_visible_target(actor, username)
    credits_amount = body.amount_yuan * pricing.CREDITS_PER_YUAN
    result = ledger.record_topup(
        username,
        amount_yuan=body.amount_yuan,
        credits_amount=credits_amount,
        note=body.note or f"充值 {body.amount_yuan} 元",
        actor=actor,
    )
    return {
        "status": "success",
        "username": username,
        "id": result["id"],
        "credited": result["credits"],
        "balance": pricing.as_credits(ledger.balance(username)),
    }


@router.get("/api/admin/accounts/{username}/credits")
def account_credits(username: str, actor: str = Depends(require_staff)):
    record = _require_visible_target(actor, username)
    return {
        "username": username,
        "plan": record.get("plan", "metered"),
        "billing_cycle": record.get("billing_cycle", "prepaid"),
        "credits": pricing.as_credits(record.get("credits_balance", 0) or 0),
        "status": record.get("status", "active"),
        "ledger": ledger.recent_ledger(username, limit=50),
        "usage": ledger.usage_rows(username, days=30),
    }


@router.get("/api/admin/usage")
def usage_overview(actor: str = Depends(require_staff)):
    """按账号的用量与余额一览：管理面板的行为监控页直接用这一份。"""
    accounts = account_store.get_all_users()
    if (get_user_record(actor) or {}).get("role") != "sudo":
        accounts = [row for row in accounts if row.get("owner") == actor]
    names = [row["username"] for row in accounts]
    usage = ledger.usage_for_many(names, days=30)
    return {
        "accounts": [
            {
                "username": row["username"],
                "plan": row.get("plan", "metered"),
                "billing_cycle": row.get("billing_cycle", "prepaid"),
                "status": row.get("status", "active"),
                "credits": pricing.as_credits(row.get("credits_balance", 0) or 0),
                "usage": usage.get(row["username"], []),
            }
            for row in accounts
        ]
    }


# ─── Business：母账号给子账号分配预算 ─────────────────────────────────────


@router.get("/api/business/subaccounts")
def list_subaccounts(user: str = Depends(get_current_user)):
    record = get_user_record(user) or {}
    if record.get("plan") != "business":
        raise HTTPException(403, "仅 Business 账号可管理子账号")
    children = [row for row in account_store.get_all_users() if row.get("owner") == user]
    usage = ledger.usage_for_many([row["username"] for row in children], days=30)
    return {
        "parent_credits": pricing.as_credits(record.get("credits_balance", 0) or 0),
        "max_users": record.get("max_users"),
        "subaccounts": [
            {
                "username": row["username"],
                "status": row.get("status", "active"),
                "credits": pricing.as_credits(row.get("credits_balance", 0) or 0),
                "quota": (
                    pricing.as_credits(row["credit_quota"])
                    if row.get("credit_quota") is not None
                    else None
                ),
                "usage": usage.get(row["username"], []),
            }
            for row in children
        ],
    }


@router.post("/api/business/subaccounts/{username}/credits")
def allocate(
    username: str,
    body: Grant,
    user: str = Depends(get_current_user),
):
    """母账号把池子里的 credits 划给子账号。"""
    record = get_user_record(user) or {}
    if record.get("plan") != "business":
        raise HTTPException(403, "仅 Business 账号可分配预算")
    target = get_user_record(username)
    if not target or target.get("owner") != user:
        raise HTTPException(404, "子账号不存在或不属于你")
    if body.credits <= 0:
        raise HTTPException(422, "分配额度必须大于 0")
    ok, message = ledger.transfer_to_child(user, username, body.credits, actor=user)
    if not ok:
        raise HTTPException(409, message)
    return {
        "status": "success",
        "username": username,
        "parent_credits": pricing.as_credits(ledger.balance(user)),
        "child_credits": pricing.as_credits(ledger.balance(username)),
    }


class SubaccountCreate(Body):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6, max_length=1024)


class SubaccountStatus(Body):
    status: str = Field(pattern="^(active|suspended)$")


@router.post("/api/business/subaccounts")
def create_subaccount(body: SubaccountCreate, user: str = Depends(get_current_user)):
    """Business 母账号创建自己的子账号。

    权限规则与 auth.upsert_account 里那条业务支线一致：只能建普通用户、
    受自己的 max_users 约束、owner 指向自己。
    """
    from auth import upsert_account

    ok, message = upsert_account(user, body.username, body.password, role="user")
    if not ok:
        raise HTTPException(409, message)
    return {"status": "success", "message": message, "username": body.username}


@router.patch("/api/business/subaccounts/{username}/status")
def set_subaccount_status(
    username: str,
    body: SubaccountStatus,
    user: str = Depends(get_current_user),
):
    """Business 母账号停用/启用自己创建的某个子账号。

    与 staff 那条端点共用一套规则（只能管自己名下的账号、不能停自己），
    区别只是调用者的身份来自 plan=business 而不是角色。
    """
    from auth import set_account_status

    success, message = set_account_status(user, username, body.status)
    if not success:
        raise HTTPException(409, message)
    return {"status": "success", "message": message}
