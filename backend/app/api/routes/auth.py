import asyncio
import hashlib
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.dependencies import check_origin, verify_token
from backend.app.infrastructure.store import store
from backend.app.security import auth

router = APIRouter(prefix="/auth", tags=["Authentication"])


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=128)


@router.post("/register")
async def register(body: Credentials, request: Request):
    check_origin(request)
    if os.getenv("AUTH_ALLOW_REGISTER", "true").lower() != "true":
        raise HTTPException(403, "注册暂未开放")
    await asyncio.to_thread(
        auth.rate_limit,
        "register:" + (request.client.host if request.client else "unknown"),
        5,
        3600,
    )
    user = await asyncio.to_thread(auth.create_user, body.username, body.password)
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response):
    check_origin(request)
    user, token = await asyncio.to_thread(
        auth.login,
        body.username,
        body.password,
        request.client.host if request.client else "unknown",
    )
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        max_age=auth.SESSION_SECONDS,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
    )
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/me")
def me(user: auth.Principal = Depends(verify_token)):
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/logout")
def logout(request: Request, response: Response, user=Depends(verify_token)):
    with store.connect() as db:
        db.execute(
            "DELETE FROM auth_sessions WHERE token_hash=?",
            (hashlib.sha256(request.cookies[auth.COOKIE_NAME].encode()).hexdigest(),),
        )
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return {"message": "已退出登录"}
