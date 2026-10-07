"""
模块描述：后台管理 API，覆盖使用日志、账号层级管理与在线设备。

权限作用域：sudo 可见全部账号/日志/设备；admin 只管理自己创建的 user 与其设备；
user 无权访问（由 require_staff / require_sudo 拦截）。
"""

from collections import deque
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette.concurrency import run_in_threadpool

from auth import (
    ROLE_SUDO,
    delete_account,
    get_user_record,
    get_user_role,
    list_accounts,
    list_sessions,
    revoke_session_by_fingerprint,
    session_fingerprint,
    set_account_limits,
    set_account_status,
    upsert_account,
)
from billing import pricing
from schemas import AccountLimitsRequest, AccountRequest, AccountStatusRequest
from services.app_security import clear_usage_logs, get_usage_log_path
from services.auth_dependencies import require_staff, require_sudo


router = APIRouter()


def _read_admin_logs(ip: str | None, ignore_heartbeat: bool) -> list[str]:
    """Read the rotated active log without retaining an attacker-sized file."""
    logs: deque[str] = deque(maxlen=1000)
    log_file = get_usage_log_path()
    if not log_file.exists():
        return []

    with log_file.open("r", encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.rstrip("\r\n")
            if ignore_heartbeat and "/api/heartbeat" in line:
                continue
            if ip:
                # Current usage lines are ``timestamp | level | ip | ...``.
                # Compare the dedicated field rather than an arbitrary substring
                # which could match a username or request path.
                fields = line.split(" | ")
                if len(fields) < 3 or fields[2] != ip:
                    continue
            logs.append(line)
    return list(reversed(logs))


@router.get("/api/admin/logs")
async def get_admin_logs(
    ip: Optional[str] = Query(default=None, max_length=64),
    ignore_heartbeat: bool = False,
    admin_user: str = Depends(require_sudo),
):
    logs = await run_in_threadpool(_read_admin_logs, ip, ignore_heartbeat)
    return {"status": "success", "logs": logs}


@router.delete("/api/admin/logs")
async def clear_admin_logs(admin_user: str = Depends(require_sudo)):
    cleared_count = await run_in_threadpool(clear_usage_logs)
    return {"status": "success", "message": "日志已清空", "cleared_files": cleared_count}


@router.get("/api/admin/accounts")
async def get_admin_accounts(admin_user: str = Depends(require_staff)):
    from infra import throttle

    accounts = await run_in_threadpool(list_accounts, admin_user)
    # 谁正被登录锁定：列表里直接给出剩余秒数，管理员才知道该解锁谁。
    locks = await run_in_threadpool(
        throttle.locked_map, [account["username"] for account in accounts]
    )
    for account in accounts:
        # micro-credit 只留在库内；控制台看到的是 credits 余额。
        account["credits"] = pricing.as_credits(account.pop("credits_balance", 0) or 0)
        account["plan"] = account.get("plan") or "metered"
        account["billing_cycle"] = account.get("billing_cycle") or "prepaid"
        account["status"] = account.get("status") or "active"
        account["locked_seconds"] = locks.get(account["username"], 0)
    return {"status": "success", "accounts": accounts}


@router.post("/api/admin/accounts")
async def set_admin_accounts(req: AccountRequest, admin_user: str = Depends(require_staff)):
    success, msg = await run_in_threadpool(
        upsert_account,
        admin_user,
        req.username,
        req.password,
        req.role,
        req.max_online,
        req.max_users,
        req.user_max_online,
        req.plan,
        req.billing_cycle,
        req.credit_multiplier,
        req.initial_credits,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.post("/api/admin/accounts/{username}/unlock")
def unlock_admin_account(
    username: str = Path(min_length=1, max_length=128),
    admin_user: str = Depends(require_staff),
):
    """立刻解除某个账号的登录锁定（账号桶 + 它名下全部来源桶）。

    用户自己连着输错密码被锁两小时是常见误操作，线上不该只能干等。
    管理员只能解锁自己有权限管理的账号。

    同步端点：权限判定与解锁都要查库，交给 FastAPI 的线程池执行，不阻塞事件循环。
    """
    from infra import throttle

    # 权限与「停用/启用」一致：staff 管自己名下的账号，sudo 不限。
    if get_user_role(admin_user) != ROLE_SUDO:
        target = get_user_record(username)
        if not target or target.get("owner") != admin_user:
            raise HTTPException(403, "只能管理自己创建的账号")
    cleared = throttle.unlock(username)
    return {"status": "success", "message": f"已解除锁定（清理 {cleared} 个节流桶）"}


@router.patch("/api/admin/accounts/{username}/status")
async def patch_admin_account_status(
    req: AccountStatusRequest,
    username: str = Path(min_length=1, max_length=128),
    admin_user: str = Depends(require_staff),
):
    """停用/启用账号；停用会立即撤销该账号的全部会话。"""
    success, msg = await run_in_threadpool(
        set_account_status, admin_user, username, req.status
    )
    if not success:
        # 越权要与格式错误分开：客户端和监控靠状态码区分，unlock 端点同样返 403。
        if msg == "只能管理自己创建的账号":
            raise HTTPException(status_code=403, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.patch("/api/admin/accounts/{username}/limits")
async def patch_admin_account_limits(
    req: AccountLimitsRequest,
    username: str = Path(min_length=1, max_length=128),
    admin_user: str = Depends(require_sudo),
):
    success, msg = await run_in_threadpool(
        set_account_limits,
        admin_user,
        username,
        req.max_online,
        req.max_users,
        req.user_max_online,
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.delete("/api/admin/accounts/{username}")
async def delete_admin_account(
    username: str = Path(min_length=1, max_length=128),
    admin_user: str = Depends(require_staff),
):
    if username == admin_user:
        raise HTTPException(status_code=400, detail="不能在登录状态下删除自己")
    success, msg = await run_in_threadpool(delete_account, username, admin_user)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.get("/api/admin/sessions")
async def get_admin_sessions(admin_user: str = Depends(require_staff)):
    sessions = await run_in_threadpool(list_sessions, admin_user)
    # sid 就是会话凭据本身：列表只出不可逆摘要，原值不进前端内存/代理/抓包日志；
    # 「下线设备」按摘要定位（见 DELETE 路由）。
    for session in sessions:
        session["sid_fingerprint"] = session_fingerprint(session.pop("sid"))
    return {"status": "success", "sessions": sessions}


@router.delete("/api/admin/sessions/{sid_fingerprint}")
async def delete_admin_session(
    sid_fingerprint: str = Path(min_length=16, max_length=16, pattern=r"^[0-9a-f]{16}$"),
    admin_user: str = Depends(require_staff),
):
    success, msg = await run_in_threadpool(
        revoke_session_by_fingerprint, admin_user, sid_fingerprint
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.get("/api/admin/throttle")
def admin_throttle(admin_user: str = Depends(require_staff)):
    """当前仍在生效的登录节流桶。

    「谁正被限流、还剩多久」是运维在做抗爆破时必须看得见的信息——
    否则只能看到一个账号突然登不上，却不知道是锁定还是故障。
    键是摘要，接口不外泄原始用户名或来源。
    """
    from infra import throttle

    return {"status": "success", "buckets": throttle.snapshot(limit=100)}
