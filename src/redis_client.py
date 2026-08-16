import logging
from typing import Optional

from config import REDIS_HOST, REDIS_PORT

logger = logging.getLogger(__name__)

_redis = None
_redis_ok: Optional[bool] = None


async def get_redis():
    global _redis, _redis_ok
    if _redis_ok is False:
        return None
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis

        client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        await client.ping()
        _redis = client
        _redis_ok = True
        logger.info("Redis connected")
        return _redis
    except Exception as e:
        _redis_ok = False
        _redis = None
        logger.warning("Redis unavailable: %s", e)
        return None
