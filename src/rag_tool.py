"""
从 Milvus 检索 FAQ/商品知识，缓存高频问题，阈值过滤低质结果。

"""
import hashlib
import json
import logging
import time
from typing import Dict, Optional, Tuple

from embeddings import aembed_text
from init_milvus import milvus_wrapper
from redis_client import get_redis

logger = logging.getLogger(__name__)

# 默认阈值：与 graph 调用保持一致（COSINE 越大越相似）
DEFAULT_THRESHOLD = 0.5
CACHE_TTL = 3600

_memory_cache: Dict[str, Tuple[str, float]] = {}


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

    key = f"rag:{collection}:{threshold}:{hashlib.md5(query.encode('utf-8')).hexdigest()}"
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
        hits = milvus_wrapper.hybrid_search(collection, query, emb, top_k)
        # COSINE：distance 越大越相似
        texts = [t for t, dist in hits if dist is not None and float(dist) >= threshold]
        result = "\n".join(texts) if texts else "未找到相关知识"
    except Exception as e:
        logger.error("search_knowledge 失败 collection=%s: %s", collection, e)
        result = "知识检索暂时不可用，请稍后再试"

    await _cache_set(key, json.dumps(result, ensure_ascii=False))
    return result
