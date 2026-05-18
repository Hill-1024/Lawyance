"""
模块描述：认证依赖，供所有 API router 复用。
"""

from typing import Optional

from fastapi import Cookie, Depends, HTTPException

from auth import get_user_role, verify_token


def get_current_user(auth_token: Optional[str] = Cookie(None)):
    if not auth_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = verify_token(auth_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username


def require_admin(current_user: str = Depends(get_current_user)):
    role = get_user_role(current_user)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
