"""
会话持久化，解决多轮对话上下文与服务重启丢失问题。
"""
import json
import logging
import time
from typing import Dict, List, Tuple

from redis_client import get_redis

logger = logging.getLogger(__name__)

SESSION_TTL = 3600
MAX_HISTORY = 20

_memory_store: Dict[str, Tuple[List[dict], float]] = {}


class SessionManager:
    @staticmethod
    async def get_history(session_id: str) -> list:
        if not session_id:
            return []

        client = await get_redis()
        if client:
            try:
                data = await client.get(f"session:{session_id}")
                if data:
                    return json.loads(data)
                return []
            except Exception as e:
                logger.warning("读取会话失败，降级内存: %s", e)

        item = _memory_store.get(session_id)
        if not item:
            return []
        messages, expire_at = item
        if time.time() > expire_at:
            _memory_store.pop(session_id, None)
            return []
        return list(messages)

    @staticmethod
    async def save_history(session_id: str, messages: list) -> None:
        if not session_id:
            return
        trimmed = list(messages[-MAX_HISTORY:])
        payload = json.dumps(trimmed, ensure_ascii=False)

        client = await get_redis()
        if client:
            try:
                await client.set(f"session:{session_id}", payload, ex=SESSION_TTL)
                return
            except Exception as e:
                logger.warning("写入会话失败，降级内存: %s", e)

        _memory_store[session_id] = (trimmed, time.time() + SESSION_TTL)
