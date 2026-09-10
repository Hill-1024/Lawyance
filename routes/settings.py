"""
模块描述：运行时设置与 provider 状态 API，供前端 SettingsPage 调用。
"""
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from schemas import ProviderKey, RequestModel, SettingsPayload
from services.auth_dependencies import require_admin
from services.settings_service import (
    activate_llm_profile,
    clear_profile_secret,
    clear_secret,
    delete_llm_profile,
    fetch_llm_models,
    get_provider_statuses,
    get_settings,
    list_llm_profiles,
    save_llm_profile,
    set_secret,
    test_provider_connection,
    update_settings,
)

router = APIRouter()

_PROFILE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class LlmProfileWriteRequest(RequestModel):
    id: str | None = Field(default=None, min_length=1, max_length=64, pattern=_PROFILE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=4_096)
    model: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=4_096)
    enabled: bool = True
    activate: bool = False


class SecretWriteRequest(RequestModel):
    provider: ProviderKey
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    value: str = Field(min_length=1, max_length=16_384)


class SecretClearRequest(RequestModel):
    provider: ProviderKey
    key: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


@router.get("/api/settings")
async def get_settings_endpoint(admin_user: str = Depends(require_admin)):
    return await run_in_threadpool(get_settings)


@router.post("/api/settings")
async def update_settings_endpoint(
    payload: SettingsPayload,
    admin_user: str = Depends(require_admin),
):
    try:
        return await run_in_threadpool(update_settings, payload.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/settings/secret")
async def set_secret_endpoint(
    req: SecretWriteRequest,
    admin_user: str = Depends(require_admin),
):
    try:
        await run_in_threadpool(set_secret, req.provider, req.key, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success"}


@router.post("/api/settings/secret/clear")
async def clear_secret_endpoint(
    req: SecretClearRequest,
    admin_user: str = Depends(require_admin),
):
    try:
        await run_in_threadpool(clear_secret, req.provider, req.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success"}


# ─── LLM 配置档案：保存多套模型端点并一键切换 ──────────────────────────────


@router.get("/api/settings/llm/profiles")
async def list_llm_profiles_endpoint(admin_user: str = Depends(require_admin)):
    return await run_in_threadpool(list_llm_profiles)


@router.post("/api/settings/llm/profiles")
async def save_llm_profile_endpoint(
    req: LlmProfileWriteRequest,
    admin_user: str = Depends(require_admin),
):
    try:
        return await run_in_threadpool(
            save_llm_profile,
            req.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/settings/llm/profiles/{profile_id}/activate")
async def activate_llm_profile_endpoint(
    profile_id: str = Path(min_length=1, max_length=64, pattern=_PROFILE_ID_PATTERN),
    admin_user: str = Depends(require_admin),
):
    try:
        return await run_in_threadpool(activate_llm_profile, profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/settings/llm/profiles/{profile_id}/secret/clear")
async def clear_llm_profile_secret_endpoint(
    profile_id: str = Path(min_length=1, max_length=64, pattern=_PROFILE_ID_PATTERN),
    admin_user: str = Depends(require_admin),
):
    try:
        await run_in_threadpool(clear_profile_secret, profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success"}


@router.delete("/api/settings/llm/profiles/{profile_id}")
async def delete_llm_profile_endpoint(
    profile_id: str = Path(min_length=1, max_length=64, pattern=_PROFILE_ID_PATTERN),
    admin_user: str = Depends(require_admin),
):
    try:
        return await run_in_threadpool(delete_llm_profile, profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/providers/status")
async def provider_status_endpoint(admin_user: str = Depends(require_admin)):
    return await run_in_threadpool(get_provider_statuses)


@router.get("/api/providers/test/{provider}")
async def test_provider_endpoint(
    provider: ProviderKey,
    admin_user: str = Depends(require_admin),
):
    result = await run_in_threadpool(test_provider_connection, provider)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.get("/api/llm/models")
async def llm_models_endpoint(admin_user: str = Depends(require_admin)):
    return await run_in_threadpool(fetch_llm_models)
