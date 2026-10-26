"""SQL保存历史事实，Redis缓存历史镜像；按认证用户与会话隔离。"""

import asyncio
import hashlib
import json
import logging
import secrets
import time
import weakref
from contextlib import asynccontextmanager

from backend.app.infrastructure.redis import get_redis
from backend.app.infrastructure.store import store

logger = logging.getLogger(__name__)
SESSION_TTL = 3600
MAX_HISTORY = 20
MAX_FALLBACK_SESSIONS = 1000
_memory_store = {}
_locks = weakref.WeakValueDictionary()


class SessionManager:
    @staticmethod
    def key(session_id: str, user_id: str = "") -> str:
        digest = hashlib.sha256(json.dumps([user_id, session_id]).encode()).hexdigest()
        return f"sg:history:v3:{digest}"

    @staticmethod
    @asynccontextmanager
    async def lock(session_id: str, user_id: str):
        key = SessionManager.key(session_id, user_id)
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        async with lock:
            # SQLite租约是跨进程的最终互斥；Redis断开时也不会退化为仅进程内锁。
            token = secrets.token_hex(16)

            def acquire():
                with store.connect() as db:
                    db.execute(
                        "INSERT INTO leases VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET token=excluded.token,expires=excluded.expires WHERE leases.expires<?",
                        (key, token, time.time() + 180, time.time()),
                    )
                    row = db.execute("SELECT token FROM leases WHERE key=?", (key,)).fetchone()
                    return row and row["token"] == token

            if not await asyncio.to_thread(acquire):
                from fastapi import HTTPException

                raise HTTPException(409, "该会话仍有任务运行，请稍后重试")

            async def heartbeat():
                while True:
                    await asyncio.sleep(30)

                    def renew():
                        with store.connect() as db:
                            db.execute(
                                "UPDATE leases SET expires=? WHERE key=? AND token=?",
                                (time.time() + 180, key, token),
                            )

                    await asyncio.to_thread(renew)

            beat = asyncio.create_task(heartbeat())
            try:
                yield
            finally:
                beat.cancel()

                def release():
                    with store.connect() as db:
                        db.execute("DELETE FROM leases WHERE key=? AND token=?", (key, token))

                await asyncio.shield(asyncio.to_thread(release))

    @staticmethod
    async def get_history(session_id: str, user_id: str = "") -> list:
        """优先读Redis镜像；缓存丢失时从SQL恢复，再尝试进程内副本。"""
        key = SessionManager.key(session_id, user_id)

        # durable history 与执行检查点分开。Redis只作有TTL的镜像，丢失后可从SQL恢复。
        def durable():
            with store.connect() as db:
                rows = db.execute(
                    "SELECT role,content FROM history WHERE user_id=? AND session_id=? ORDER BY created DESC,rowid DESC LIMIT ?",
                    (user_id, session_id, MAX_HISTORY),
                ).fetchall()
                return [dict(row) for row in reversed(rows)]

        client = await get_redis()
        if client:
            try:
                data = await client.get(key)
                if data:
                    return json.loads(data)
            except Exception:
                logger.warning("读取 Redis 会话失败，尝试内存副本")
        persisted = await asyncio.to_thread(durable)
        if persisted:
            return persisted
        messages, expires = _memory_store.get(key, ([], 0))
        if time.time() >= expires:
            _memory_store.pop(key, None)
            return []
        return [dict(message) for message in messages]

    @staticmethod
    async def save_history(
        session_id: str, messages: list, user_id: str = "", run_id: str | None = None
    ):
        """先裁剪到20条并更新副本，再写Redis及1小时TTL；不保存内部工具规划。"""
        key = SessionManager.key(session_id, user_id)
        trimmed = [dict(message) for message in messages[-MAX_HISTORY:]]

        def durable():
            with store.connect() as db:
                if run_id:
                    # 每个任务仅提交一对问答；恢复/重放不会重复追加历史。
                    for index, message in enumerate(messages[-2:]):
                        db.execute(
                            "INSERT OR IGNORE INTO history VALUES(?,?,?,?,?,?)",
                            (
                                user_id,
                                session_id,
                                run_id,
                                message["role"],
                                message["content"],
                                time.time() + index * 0.000001,
                            ),
                        )
                else:
                    db.execute(
                        "DELETE FROM history WHERE user_id=? AND session_id=?",
                        (user_id, session_id),
                    )
                    for index, message in enumerate(trimmed):
                        db.execute(
                            "INSERT INTO history VALUES(?,?,?,?,?,?)",
                            (
                                user_id,
                                session_id,
                                str(index),
                                message["role"],
                                message["content"],
                                time.time() + index * 0.000001,
                            ),
                        )

        await asyncio.to_thread(durable)
        now = time.time()
        for expired in [k for k, (_, deadline) in _memory_store.items() if deadline <= now]:
            _memory_store.pop(expired, None)
        if key not in _memory_store and len(_memory_store) >= MAX_FALLBACK_SESSIONS:
            _memory_store.pop(next(iter(_memory_store)))
        _memory_store[key] = (trimmed, now + SESSION_TTL)
        client = await get_redis()
        if client:
            try:
                await client.set(key, json.dumps(trimmed, ensure_ascii=False), ex=SESSION_TTL)
            except Exception:
                logger.warning("写入 Redis 会话失败，已保留内存副本")
