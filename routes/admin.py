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
    delete_account,
    list_accounts,
    list_sessions,
    revoke_session,
    set_account_limits,
    upsert_account,
)
from schemas import AccountLimitsRequest, AccountRequest
from services.app_security import clear_usage_logs, get_usage_log_path
from services.auth_dependencies import require_staff, require_sudo


router = APIRouter()

_SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{16,128}$"


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
    accounts = await run_in_threadpool(list_accounts, admin_user)
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
    )
    if not success:
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
    return {"status": "success", "sessions": sessions}


@router.delete("/api/admin/sessions/{sid}")
async def delete_admin_session(
    sid: str = Path(min_length=16, max_length=128, pattern=_SESSION_ID_PATTERN),
    admin_user: str = Depends(require_staff),
):
    success, msg = await run_in_threadpool(revoke_session, admin_user, sid)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}
