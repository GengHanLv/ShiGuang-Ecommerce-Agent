"""按用户与会话隔离历史，Redis 持久化并提供有界的内存降级。"""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import time
import weakref
from backend.app.infrastructure.redis import get_redis

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
        return f"session:v2:{digest}"

    @staticmethod
    @asynccontextmanager
    async def lock(session_id: str, user_id: str):
        key = SessionManager.key(session_id, user_id)
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        async with lock:
            yield

    @staticmethod
    async def get_history(session_id: str, user_id: str = "") -> list:
        key = SessionManager.key(session_id, user_id)
        client = await get_redis()
        if client:
            try:
                data = await client.get(key)
                if data:
                    return json.loads(data)
            except Exception:
                logger.warning("读取 Redis 会话失败，尝试内存副本")
        messages, expires = _memory_store.get(key, ([], 0))
        if time.time() >= expires:
            _memory_store.pop(key, None)
            return []
        return [dict(message) for message in messages]

    @staticmethod
    async def save_history(session_id: str, messages: list, user_id: str = ""):
        key = SessionManager.key(session_id, user_id)
        trimmed = [dict(message) for message in messages[-MAX_HISTORY:]]
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
