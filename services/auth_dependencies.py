"""
模块描述：认证依赖，供所有 API router 复用。
"""

from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException

from auth import ROLE_ADMIN, ROLE_SUDO, get_user_role, verify_token


def get_current_user(
    auth_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """认证 token 解析：Authorization Bearer 优先于 cookie。"""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        token = auth_token
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username


def require_sudo(current_user: str = Depends(get_current_user)):
    if get_user_role(current_user) != ROLE_SUDO:
        raise HTTPException(status_code=403, detail="Sudo access required")
    return current_user


def require_staff(current_user: str = Depends(get_current_user)):
    """sudo 与 admin 均可访问；具体作用域由处理函数进一步限制。"""
    if get_user_role(current_user) not in (ROLE_SUDO, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
