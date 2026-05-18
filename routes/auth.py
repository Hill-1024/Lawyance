"""
模块描述：登录、登出与认证状态 API。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from auth import authenticate_user, create_token, get_user_role
from schemas import LoginRequest
from services.app_security import secure_cookie_for_request
from services.auth_dependencies import get_current_user


router = APIRouter()


@router.post("/api/login")
async def login(req: LoginRequest, response: Response, request: Request):
    success, msg = authenticate_user(req.username, req.password)
    if not success:
        raise HTTPException(status_code=401, detail=msg)

    token = create_token(req.username)
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=secure_cookie_for_request(request),
        max_age=7 * 24 * 3600,
        samesite="strict",
    )
    return {"status": "success", "message": "登录成功"}


@router.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(key="auth_token", httponly=True, samesite="strict")
    return {"status": "success"}


@router.get("/api/verify_auth")
async def verify_auth_endpoint(current_user: str = Depends(get_current_user)):
    return {"status": "success", "username": current_user, "role": get_user_role(current_user)}
