import asyncio

"""
从 Milvus 检索 FAQ/商品知识，缓存高频问题，阈值过滤低质结果。

"""
import hashlib
import json
import logging
import time
from typing import Dict, Optional, Tuple

from backend.app.infrastructure.embeddings import aembed_text
from backend.app.infrastructure.milvus import milvus_wrapper
from backend.app.infrastructure.redis import get_redis

logger = logging.getLogger(__name__)

# 默认阈值：与 graph 调用保持一致（COSINE 越大越相似）
DEFAULT_THRESHOLD = 0.5
CACHE_TTL = 3600

_memory_cache: Dict[str, Tuple[str, float]] = {}
_cache_versions: dict[str, int] = {}


async def cache_generation(collection: str) -> int:
    client = await get_redis()
    if client:
        try:
            return int(await client.get(f"rag:version:{collection}") or 0)
        except Exception:
            pass
    return _cache_versions.get(collection, 0)


async def invalidate_knowledge_cache(collection: str):
    version = time.time_ns()
    client = await get_redis()
    if client:
        try:
            version = int(await client.incr(f"rag:version:{collection}"))
        except Exception:
            logger.warning("知识缓存版本更新失败，已更新本地版本")
    _cache_versions[collection] = version


async def _cache_get(key: str) -> Optional[str]:
    client = await get_redis()
    if client:
        try:
            val = await client.get(key)
            return val
        except Exception as e:
            logger.warning("Redis get 失败: %s", e)
    # 内存降级
    item = _memory_cache.get(key)
    if item:
        value, expire_at = item
        if time.time() < expire_at:
            return value
        _memory_cache.pop(key, None)
    return None


async def _cache_set(key: str, value: str, ttl: int = CACHE_TTL) -> None:
    client = await get_redis()
    if client:
        try:
            await client.set(key, value, ex=ttl)
            return
        except Exception as e:
            logger.warning("Redis set 失败: %s", e)
    _memory_cache[key] = (value, time.time() + ttl)


async def search_knowledge(
    query: str,
    collection: str = "faq",
    top_k: int = 3,
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    if not query or not query.strip():
        return "未找到相关知识"

    generation = await cache_generation(collection)
    key = f"rag:{collection}:{generation}:{top_k}:{threshold}:{hashlib.md5(query.encode('utf-8')).hexdigest()}"
    cached = await _cache_get(key)
    if cached is not None:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            return cached

    try:
        emb = await aembed_text(query)
        if not emb:
            return "未找到相关知识"
        hits = await asyncio.to_thread(
            milvus_wrapper.hybrid_search,
            collection,
            query,
            emb,
            top_k,
        )
        # COSINE：distance 越大越相似
        texts = [t for t, dist in hits if dist is not None and float(dist) >= threshold]
        result = "\n".join(texts) if texts else "未找到相关知识"
    except Exception as e:
        logger.error("search_knowledge 失败 collection=%s: %s", collection, e)
        return "知识检索暂时不可用，请稍后再试"

    await _cache_set(key, json.dumps(result, ensure_ascii=False))
    return result
