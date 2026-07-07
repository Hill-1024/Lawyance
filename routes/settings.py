"""
模块描述：运行时设置与 provider 状态 API，供前端 SettingsPage 调用。
"""
from fastapi import APIRouter, Depends, HTTPException

from schemas import SettingsPayload
from services.auth_dependencies import get_current_user, require_admin
from services.settings_service import get_provider_statuses, get_settings, test_provider_connection, update_settings

router = APIRouter()


@router.get("/api/settings")
async def get_settings_endpoint(current_user: str = Depends(get_current_user)):
    return get_settings()


@router.post("/api/settings")
async def update_settings_endpoint(
    payload: SettingsPayload,
    admin_user: str = Depends(require_admin),
):
    try:
        return update_settings(payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/providers/status")
async def provider_status_endpoint(_current_user: str = Depends(get_current_user)):
    return get_provider_statuses()


@router.get("/api/providers/test/{provider}")
async def test_provider_endpoint(
    provider: str,
    admin_user: str = Depends(require_admin),
):
    result = test_provider_connection(provider)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result
