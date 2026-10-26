"""共用 Redis 连接；失败后短暂退避，允许服务恢复后自动重连。"""

import logging
import time

from backend.app.core.config import REDIS_HOST, REDIS_PORT

logger = logging.getLogger(__name__)
_redis = None
_retry_after = 0.0


async def get_redis():
    global _redis, _retry_after
    if _redis is not None:
        return _redis
    if time.monotonic() < _retry_after:
        return None
    from redis.asyncio import Redis

    client = Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await client.ping()
        _redis = client
        return client
    except Exception:
        await client.aclose()
        _retry_after = time.monotonic() + 15
        logger.warning("Redis 暂不可用，使用进程内会话缓存")
        return None


async def close_redis():
    global _redis, _retry_after
    if _redis is not None:
        await _redis.aclose()
    _redis = None
    _retry_after = 0.0
