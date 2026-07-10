"""
模块描述：admin 日志与账号管理 API。
"""

from collections import deque
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from starlette.concurrency import run_in_threadpool

from auth import add_or_update_account, delete_account, list_accounts
from schemas import AccountRequest
from services.app_security import clear_usage_logs, get_usage_log_path
from services.auth_dependencies import require_admin


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
    admin_user: str = Depends(require_admin),
):
    logs = await run_in_threadpool(_read_admin_logs, ip, ignore_heartbeat)
    return {"status": "success", "logs": logs}


@router.delete("/api/admin/logs")
async def clear_admin_logs(admin_user: str = Depends(require_admin)):
    cleared_count = await run_in_threadpool(clear_usage_logs)
    return {"status": "success", "message": "日志已清空", "cleared_files": cleared_count}


@router.get("/api/admin/accounts")
async def get_admin_accounts(admin_user: str = Depends(require_admin)):
    accounts = await run_in_threadpool(list_accounts)
    return {"status": "success", "accounts": accounts}


@router.post("/api/admin/accounts")
async def set_admin_accounts(req: AccountRequest, admin_user: str = Depends(require_admin)):
    success, msg = await run_in_threadpool(
        add_or_update_account,
        req.username,
        req.password,
        req.role or "user",
    )
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.delete("/api/admin/accounts/{username}")
async def delete_admin_account(
    username: str = Path(min_length=1, max_length=128),
    admin_user: str = Depends(require_admin),
):
    if username == admin_user:
        raise HTTPException(status_code=400, detail="不能在登录状态下删除自己")
    success, msg = await run_in_threadpool(delete_account, username)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}
