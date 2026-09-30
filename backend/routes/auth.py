"""
模块描述：登录、登出与认证状态 API。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from auth import (
    ROLE_ADMIN,
    authenticate_user,
    change_password,
    count_online,
    create_session,
    get_user_limits,
    get_user_role,
    hash_client_identity,
    revoke_token_session,
    verify_token,
)
from schemas import ChangePasswordRequest, LoginRequest
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
