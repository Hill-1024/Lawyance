"""
模块描述：登录、登出、认证状态与个人资料（自定义 ID / 头像）API。
"""

import re

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import Response as FastAPIResponse
from starlette.concurrency import run_in_threadpool

from auth import (
    ROLE_ADMIN,
    authenticate_user,
    change_password,
    clear_user_avatar,
    count_online,
    create_session,
    get_account_profile,
    get_user_avatar_by_uid,
    get_user_limits,
    get_user_role,
    hash_client_identity,
    revoke_token_session,
    update_avatar,
    update_custom_id,
    verify_token,
)
from schemas import ChangePasswordRequest, LoginRequest, ProfileUpdateRequest
from services.app_security import (
    client_ip_for_request,
    secure_cookie_for_request,
)
from services.auth_dependencies import get_current_user


router = APIRouter()


def is_native_client_request(request: Request) -> bool:
    """来源控制交由网关层，应用内只按客户端声明识别原生端（以便返回 bearer token）。"""
    client_type = (request.headers.get("x-lawver-client") or "").strip().lower()
    return client_type == "capacitor"


def _extract_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.cookies.get("auth_token")


@router.post("/api/login")
async def login(req: LoginRequest, response: Response, request: Request):
    success, msg = await run_in_threadpool(
        authenticate_user,
        req.username,
        req.password,
        client_ip_for_request(request),
    )
    if not success:
        raise HTTPException(status_code=401, detail=msg)

    session_ok, session_msg, sid, _evicted = await run_in_threadpool(
        create_session,
        req.username,
        client=((request.headers.get("x-lawver-client") or "web").strip() or "web"),
        user_agent=(request.headers.get("user-agent") or "")[:512],
        ip_hash=hash_client_identity(client_ip_for_request(request)),
    )
    if not session_ok:
        raise HTTPException(status_code=429, detail=session_msg)

    # 会话凭据就是 sid 本身：没有 JWT，撤销即删行。
    token = sid
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=secure_cookie_for_request(request),
        max_age=7 * 24 * 3600,
        samesite="strict",
    )
    payload = {
        "status": "success",
        "message": "登录成功",
        "username": req.username,
        "role": await run_in_threadpool(get_user_role, req.username),
    }
    if is_native_client_request(request):
        payload["token"] = token
    return payload


@router.post("/api/logout")
async def logout(response: Response, request: Request):
    token = _extract_token(request)
    if token:
        await run_in_threadpool(revoke_token_session, token)
    response.delete_cookie(
        key="auth_token",
        httponly=True,
        secure=secure_cookie_for_request(request),
        samesite="strict",
    )
    return {"status": "success"}


@router.get("/api/verify_auth")
async def verify_auth_endpoint(current_user: str = Depends(get_current_user)):
    role = get_user_role(current_user)
    limits = get_user_limits(current_user)
    payload = {
        "status": "success",
        "username": current_user,
        "role": role,
        "max_online": limits.get("max_online"),
        "online_count": count_online(current_user),
    }
    if role == ROLE_ADMIN:
        payload["max_users"] = limits.get("max_users")
        payload["user_max_online"] = limits.get("user_max_online")
    return payload


@router.get("/api/session")
async def session_probe(request: Request):
    """登录态探测：**永远 200**，用 authenticated 字段表达结果。

    前端启动时探一次登录态。走 /api/verify_auth 的话未登录必然 401，而浏览器把每个
    4xx 资源响应都记进 console error——每个新用户一打开登录页都有一条噪音，
    排障时反而盖住真错误。这里不抛错，也就不产生噪音。
    """
    token = _extract_token(request)
    username = await run_in_threadpool(verify_token, token) if token else None
    if not username:
        return {"authenticated": False}
    profile = await run_in_threadpool(get_account_profile, username)
    return {
        "authenticated": True,
        "username": username,
        "role": await run_in_threadpool(get_user_role, username),
        # 介绍页账户卡片与个人资料设置共用这一份：uid 稳定标识、custom_id 展示句柄、
        # plan 决定头像旁的订阅徽标、avatar_version 作头像缓存失效。
        "uid": (profile or {}).get("uid"),
        "custom_id": (profile or {}).get("custom_id"),
        "plan": (profile or {}).get("plan", "metered"),
        "avatar_version": (profile or {}).get("avatar_version", 0),
    }


# ─── 个人资料（自定义 ID / 头像）──────────────────────────────────────────


@router.get("/api/profile")
async def read_profile(current_user: str = Depends(get_current_user)):
    profile = await run_in_threadpool(get_account_profile, current_user)
    if not profile:
        raise HTTPException(status_code=404, detail="账号不存在")
    return profile


@router.patch("/api/profile")
async def update_profile(
    req: ProfileUpdateRequest,
    current_user: str = Depends(get_current_user),
):
    if "custom_id" not in req.model_fields_set:
        raise HTTPException(status_code=422, detail="没有可更新的字段。")
    ok, error = await run_in_threadpool(
        update_custom_id, current_user, req.custom_id
    )
    if not ok:
        status = 409 if "已被占用" in error else 422
        raise HTTPException(status_code=status, detail=error)
    profile = await run_in_threadpool(get_account_profile, current_user)
    return {"status": "success", "profile": profile}


@router.put("/api/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user),
):
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    data = await file.read()
    version, error = await run_in_threadpool(update_avatar, current_user, data, content_type)
    if version is None:
        raise HTTPException(status_code=422, detail=error)
    profile = await run_in_threadpool(get_account_profile, current_user)
    return {"status": "success", "profile": profile}


@router.delete("/api/profile/avatar")
async def remove_avatar(current_user: str = Depends(get_current_user)):
    await run_in_threadpool(clear_user_avatar, current_user)
    profile = await run_in_threadpool(get_account_profile, current_user)
    return {"status": "success", "profile": profile}


@router.get("/api/avatars/{uid}")
async def serve_avatar(uid: str):
    """公开头像：uid 是 32 位不可枚举标识，作为 URL 已是能力凭证。

    version 走查询参数失效缓存，所以本体可以给一段较长的不可变缓存。
    """
    if not re.fullmatch(r"[0-9a-f]{32}", uid):
        raise HTTPException(status_code=404, detail="头像不存在")
    avatar = await run_in_threadpool(get_user_avatar_by_uid, uid)
    if not avatar:
        raise HTTPException(status_code=404, detail="头像不存在")
    return FastAPIResponse(
        content=avatar["data"],
        media_type=avatar["content_type"] or "image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": "inline",
        },
    )
    return {
        "authenticated": True,
        "username": username,
        "role": await run_in_threadpool(get_user_role, username),
    }


@router.post("/api/password")
async def change_password_endpoint(
    req: ChangePasswordRequest,
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """用户自助改密：需要当前密码；改完保留当前设备，其他设备下线。"""
    success, message, revoked = await run_in_threadpool(
        change_password,
        current_user,
        req.current_password,
        req.new_password,
        keep_sid=_extract_token(request) or None,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message, "revoked_sessions": revoked}
