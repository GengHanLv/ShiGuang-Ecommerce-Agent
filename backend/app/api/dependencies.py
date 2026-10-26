from fastapi import Depends, HTTPException, Request

from backend.app.core.config import CORS_ORIGINS
from backend.app.security.auth import Principal, principal_for


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
        own = str(request.base_url).rstrip("/")
        if origin not in {*CORS_ORIGINS, own}:
            raise HTTPException(403, "请求来源不受信任")


def verify_token(request: Request) -> Principal:
    """旧函数名保留为依赖入口，彻底移除共享API Key的用户认证回退。"""
    check_origin(request)
    return principal_for(request)


def require_admin(user: Principal = Depends(verify_token)):
    if user.role != "admin":
        raise HTTPException(403, "此操作需要管理员权限")
    return user
