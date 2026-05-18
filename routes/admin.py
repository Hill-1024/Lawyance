"""
模块描述：admin 日志与账号管理 API。
"""

from typing import Optional
import os

from fastapi import APIRouter, Depends, HTTPException

from auth import add_or_update_account, delete_account, list_accounts
from schemas import AccountRequest
from services.auth_dependencies import require_admin


router = APIRouter()


@router.get("/api/admin/logs")
async def get_admin_logs(
    ip: Optional[str] = None,
    ignore_heartbeat: bool = False,
    admin_user: str = Depends(require_admin),
):
    logs = []
    log_file = "data/usage.log"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if ip and ip not in line:
                    continue
                if ignore_heartbeat and "/api/heartbeat" in line:
                    continue
                logs.append(line.strip())
    return {"status": "success", "logs": logs[::-1][:1000]}


@router.get("/api/admin/accounts")
async def get_admin_accounts(admin_user: str = Depends(require_admin)):
    return {"status": "success", "accounts": list_accounts()}


@router.post("/api/admin/accounts")
async def set_admin_accounts(req: AccountRequest, admin_user: str = Depends(require_admin)):
    success, msg = add_or_update_account(req.username, req.password, req.role or "user")
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@router.delete("/api/admin/accounts/{username}")
async def delete_admin_account(username: str, admin_user: str = Depends(require_admin)):
    if username == admin_user:
        raise HTTPException(status_code=400, detail="不能在登录状态下删除自己")
    success, msg = delete_account(username)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}
