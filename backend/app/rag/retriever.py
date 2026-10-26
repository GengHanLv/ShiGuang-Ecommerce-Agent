"""Milvus稠密召回 + 独立BM25召回 + RRF，返回可追溯证据。"""

import asyncio
import hashlib
import json
import logging
import os
import time

from backend.app.core.config import CHAT_MODEL
from backend.app.infrastructure.embeddings import aembed_text
from backend.app.infrastructure.milvus import milvus_wrapper
from backend.app.infrastructure.redis import get_redis
from backend.app.infrastructure.store import store
from backend.app.rag.catalog import catalog, metadata
from backend.app.rag.corpus import active_retrieval_filter
from backend.app.rag.entities import matches, parse_scope, scalar_filter
from backend.app.rag.metadata import SCALAR_FIELDS
from backend.app.rag.ranking import bm25, reciprocal_rank_fusion
from backend.app.rag.reranker import assess_evidence, rerank
from backend.app.rag.schema import physical_collection, structured

logger = logging.getLogger(__name__)
DEFAULT_THRESHOLD = 0.5  # 仅用于原始稠密余弦分数，不能套用到RRF。
CACHE_TTL = 3600
_memory_cache = {}
_cache_versions = {}
_sync_locks = {}


def selected_platform(query, platform="all"):
    if platform not in {"all", "jd", "tmall", "pdd"}:
        raise ValueError("无效平台")
    if platform != "all":
        return platform
    names = [
        key for word, key in [("京东", "jd"), ("天猫", "tmall"), ("拼多多", "pdd")] if word in query
    ]
    return names[0] if len(names) == 1 else "all"


def retrieval_filter(platform):
    pieces = [active_retrieval_filter()]
    label = {"jd": "京东", "tmall": "天猫", "pdd": "拼多多"}.get(platform)
    if label:
        pieces.append("text like " + json.dumps("【" + label + "知识｜%", ensure_ascii=False))
    return " and ".join("(" + part + ")" for part in pieces if part)


async def cache_generation(collection):
    def read():
        with store.connect() as db:
            row = db.execute(
                "SELECT version FROM cache_versions WHERE collection=?", (collection,)
            ).fetchone()
            return row["version"] if row else 0

    return await asyncio.to_thread(read)


async def invalidate_knowledge_cache(collection):
    version = time.time_ns()

    def write():
        with store.connect() as db:
            db.execute(
                "INSERT INTO cache_versions VALUES(?,?) ON CONFLICT(collection) DO UPDATE SET version=excluded.version",
                (collection, version),
            )

    await asyncio.to_thread(write)
    _cache_versions[collection] = version


async def _cache_get(key):
    client = await get_redis()
    if client:
        try:
            return await client.get(key)
        except Exception:
            pass
    item = _memory_cache.get(key)
    if item and item[1] > time.time():
        return item[0]
    _memory_cache.pop(key, None)
    return None


async def _cache_set(key, value, ttl=CACHE_TTL):
    client = await get_redis()
    if client:
        try:
            await client.set(key, value, ex=ttl)
            return
        except Exception:
            pass
    # 兜底也要有界，避免外部不同问题不断撑大内存。
    if len(_memory_cache) >= 1000:
        _memory_cache.pop(next(iter(_memory_cache)))
    _memory_cache[key] = (value, time.time() + ttl)


def sync_catalog(collection, generation):
    snapshot_generation = str(generation) + ":" + physical_collection(collection)
    if catalog.fresh(collection, snapshot_generation):
        return
    client = milvus_wrapper.client
    physical = physical_collection(collection)
    milvus_wrapper.ensure_loaded(physical)
    iterator = client.query_iterator(
        collection_name=physical,
        filter=active_retrieval_filter(),
        output_fields=["id", "text", *SCALAR_FIELDS] if structured(collection) else ["id", "text"],
        batch_size=256,
    )
    rows = []
    try:
        while batch := iterator.next():
            rows.extend(batch)
    finally:
        iterator.close()
    catalog.replace_snapshot(collection, rows, snapshot_generation)


async def retrieve(
    query,
    collection="faq",
    top_k=3,
    threshold=DEFAULT_THRESHOLD,
    platform="all",
    *,
    original_query=None,
):
    if collection not in {"faq", "product_knowledge"}:
        raise ValueError("不允许检索该集合")
    if not query.strip():
        return []
    if not 1 <= top_k <= 10:
        raise ValueError("top_k须在1到10之间")
    platform = selected_platform(query, platform)
    generation = await cache_generation(collection)
    policy = hashlib.sha256(retrieval_filter(platform).encode()).hexdigest()[:12]
    scope = (
        parse_scope(original_query or query)
        if collection == "product_knowledge"
        else parse_scope("")
    )
    if collection == "product_knowledge" and not scope.models:
        scope.models = parse_scope(query).models
    signature = hashlib.sha256(
        json.dumps(
            [query, original_query, scope.json(), os.getenv("RAG_RERANKER", "llm"), CHAT_MODEL],
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    key = f"sg:cache:rag:v6:{physical_collection(collection)}:{generation}:{platform}:{top_k}:{threshold}:{policy}:{signature}"
    cached = await _cache_get(key)
    if cached is not None:
        return json.loads(cached)
    lock = _sync_locks.setdefault(collection, asyncio.Lock())
    async with lock:
        await asyncio.to_thread(sync_catalog, collection, generation)
    rows = await asyncio.to_thread(catalog.rows, collection)
    rows = [
        r
        for r in rows
        if (platform == "all" or r["metadata"]["platform"] == platform)
        and matches(r["metadata"], scope)
    ]
    rowmap = {r["vector_id"]: r for r in rows}
    vector = await aembed_text(query)
    # 两路独立生成候选：BM25能找回没有进入向量Top-N的型号词。
    dense_hits = await asyncio.to_thread(
        milvus_wrapper.dense_search_hits,
        physical_collection(collection),
        vector,
        top_k=max(15, top_k * 4),
        filter_expr=" and ".join(
            "(" + p + ")" for p in (active_retrieval_filter(), scalar_filter(scope, platform)) if p
        )
        if structured(collection)
        else retrieval_filter(platform),
        output_fields=["text", *SCALAR_FIELDS] if structured(collection) else ["text"],
    )
    dense = [(str(h["id"]), h["score"]) for h in dense_hits if h["score"] >= threshold]
    sparse = await asyncio.to_thread(bm25, query, rows, max(15, top_k * 4))
    # 补齐镜像刷新间隙里的稠密结果，不把新内容静默丢掉。
    for hit in dense_hits:
        identifier = str(hit["id"])
        if identifier not in rowmap:
            rowmap[identifier] = {
                "text": hit["text"],
                "metadata": metadata(hit["text"]) | {k: hit[k] for k in SCALAR_FIELDS if k in hit},
            }
    ds = dict(dense)
    ss = dict(sparse)
    result = []
    for identifier, rank_score in reciprocal_rank_fusion(dense, sparse):
        row = rowmap.get(identifier)
        if not row:
            continue
        if (platform != "all" and row["metadata"].get("platform") != platform) or not matches(
            row["metadata"], scope
        ):
            continue
        # 来源/内容去重，而不是仅按数值分数去重。
        if any(item["text"] == row["text"] for item in result):
            continue
        result.append(
            {
                "id": identifier,
                "collection": collection,
                "text": row["text"],
                **row["metadata"],
                "dense_score": ds.get(identifier),
                "bm25_score": ss.get(identifier),
                "rrf_score": round(rank_score, 7),
            }
        )
        if len(result) >= 16:
            break
    result = (await rerank(original_query or query, result, scope))[:top_k]
    await _cache_set(key, json.dumps(result, ensure_ascii=False))
    return result


async def search_knowledge(
    query,
    collection="faq",
    top_k=3,
    threshold=DEFAULT_THRESHOLD,
    *,
    platform="all",
    original_query=None,
):
    """向工具输出JSON证据，保留source_id、平台和URL，便于最后回答引用。"""
    try:
        hits = await retrieve(
            query, collection, top_k, threshold, platform, original_query=original_query
        )
        return (
            json.dumps(
                {"evidence": hits, "assessment": assess_evidence(original_query or query, hits)},
                ensure_ascii=False,
            )
            if hits
            else json.dumps(
                {"evidence": [], "assessment": assess_evidence(query, [])}, ensure_ascii=False
            )
        )
    except Exception:
        logger.exception("知识检索失败 collection=%s", collection)
        return "知识检索暂时不可用，请稍后再试；当前不能确认相关事实。"
