"""密码使用 scrypt，浏览器只持有 HttpOnly 随机会话；用户身份始终由会话反查。"""

import hashlib
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request

from backend.app.core.config import DATA_DIR
from backend.app.infrastructure.store import store

COOKIE_NAME = "shiguang_session"
SESSION_SECONDS = 60 * 60 * 12


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    role: str


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def check_password(password, encoded):
    try:
        _, salt, expected = encoded.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return secrets.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_user(username, password, *, role="user", user_id=None):
    username = username.strip().casefold()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", username):
        raise HTTPException(422, "用户名需为3至40位字母、数字、点、下划线或横线")
    if not 10 <= len(password) <= 128:
        raise HTTPException(422, "密码长度需为10至128位")
    identifier = user_id or uuid.uuid4().hex
    encoded = hash_password(password)
    with store.connect() as db:
        # 写入主键和唯一用户名由数据库最终约束，并发注册也无法抢占身份。
        import sqlite3

        try:
            db.execute(
                "INSERT INTO users VALUES(?,?,?,?,?)",
                (identifier, username, encoded, role, time.time()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "用户名已存在") from exc
    return Principal(identifier, username, role)


def bootstrap_admin():
    with store.connect() as db:
        if db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            return
    username = os.getenv("AUTH_ADMIN_USERNAME", "admin")
    password = os.getenv("AUTH_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
    # 首个管理员接管现有演示订单的 user123 身份；普通注册只能得到随机用户ID。
    try:
        user = create_user(
            username, password, role="admin", user_id=os.getenv("AUTH_ADMIN_USER_ID", "user123")
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            with store.connect() as db:
                if db.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
                    return
        raise
    path = DATA_DIR / "auth/bootstrap-admin.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"username": user.username, "password": password}, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


def rate_limit(key, limit=10, window=300):
    now = time.time()
    key = hashlib.sha256(key.encode()).hexdigest()
    with store.connect() as db:
        db.execute("DELETE FROM login_attempts WHERE expires<?", (now,))
        row = db.execute("SELECT * FROM login_attempts WHERE key=?", (key,)).fetchone()
        if row and row["attempts"] >= limit:
            raise HTTPException(429, "尝试次数过多，请稍后再试")
        db.execute(
            "INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1",
            (key, now + window),
        )


def login(username, password, remote):
    rate_limit("login:" + remote + ":" + username.casefold())
    with store.connect() as db:
        row = db.execute(
            "SELECT * FROM users WHERE username=?", (username.strip().casefold(),)
        ).fetchone()
    # 未注册用户名也执行同强度散列，避免快速枚举有效账户。
    encoded = row["password_hash"] if row else hash_password("unregistered-account")
    if not check_password(password, encoded) or row is None:
        raise HTTPException(401, "用户名或密码不正确")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with store.connect() as db:
        db.execute("DELETE FROM auth_sessions WHERE expires<?", (time.time(),))
        db.execute(
            "INSERT INTO auth_sessions VALUES(?,?,?)",
            (digest, row["id"], time.time() + SESSION_SECONDS),
        )
    return Principal(row["id"], row["username"], row["role"]), token


def principal_for(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    if not token or len(token) > 256:
        raise HTTPException(401, "请先登录")
    with store.connect() as db:
        row = db.execute(
            "SELECT u.id,u.username,u.role FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()
    if not row:
        raise HTTPException(401, "登录已失效，请重新登录")
    return Principal(**dict(row))
