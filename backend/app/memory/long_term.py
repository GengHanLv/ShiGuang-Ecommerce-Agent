"""用户级长期记忆：召回、抽取与同主题更新；规则清洗见 policy.py。"""

import asyncio
import logging

from backend.app.core.config import CHAT_MODEL
from backend.app.core.models import get_openai_client
from backend.app.infrastructure.embeddings import aembed_text
from backend.app.infrastructure.milvus import milvus_wrapper
from backend.app.memory.policy import (
    VALID_TYPES,
    _collapse_topic_conflicts,
    _filter_items,
    _is_noise_memory_text,
    _normalize_memory_text,
    _parse_extract_output,
    _should_attempt_extract,
    _strip_type_prefix,
    _topic_key,
)
from backend.app.memory.preferences import delete_preference, list_preferences, set_preference
from backend.app.memory.signals import (
    is_memory_delete,
    is_memory_update,
)

logger = logging.getLogger(__name__)
MEMORY_COLLECTION = "user_memory"
DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 0.45
EXTRACT_PROMPT = """你是记忆过滤器。只从对话中抽取「跨会话仍有价值」的用户信息。

【可以抽取】
- preference：稳定偏好（如晚间收货、快递到货请电话通知、只要顺丰/指定快递公司、不要打电话）
- fact：对商品/服务的持续反馈（如曾反馈耳机降噪差、对包装过敏）

【绝对不要抽取】（匹配任一则输出 NONE）
- 订单号、待付款/已发货/已签收等实时订单状态
- 「用户查询了订单」「用户问退货流程」这类过程描述
- 单次寒暄、讲笑话、转人工
- 可从业务库随时查到的订单明细

若没有可长期保存的内容，只输出 NONE。
否则只输出 JSON 数组：[{{"type":"preference","text":"用户偏好晚间收货"}}]
text 必须是一句稳定、可复用的中文短句。

用户：{user_msg}
客服：{assistant_msg}
"""
TOPIC_SEED_QUERIES = {
    "phone_notify": "快递到货电话通知偏好",
    "recv_time": "收货时间早晚偏好",
    "express_co": "指定快递公司偏好",
}


def _escape_user_id(user_id: str) -> str:
    return user_id.replace("\\", "\\\\").replace('"', '\\"')


async def _embed(text: str) -> list | None:
    return await aembed_text(text)


async def _delete_ids(ids: list) -> int:
    ids = [i for i in ids if i is not None]
    if not ids:
        return 0
    try:
        await asyncio.to_thread(
            milvus_wrapper.client.delete, collection_name=MEMORY_COLLECTION, ids=ids
        )
        return len(ids)
    except Exception as e:
        logger.error("memory_delete ids 失败: %s", e)
        return 0


async def _replace_related_memories(user_id: str, items: list[dict], threshold: float = 0.4) -> int:
    deleted = 0
    seen_ids = set()
    for it in items:
        text = (it.get("text") or "").strip()
        if not text:
            continue
        topic = _topic_key(text)
        if topic is None:
            hits = await _search_memory_hits(user_id, text, top_k=5, threshold=0.88)
            ids = [h["id"] for h in hits if h.get("id") not in seen_ids]
            n = await _delete_ids(ids)
            seen_ids.update(ids)
            deleted += n
            continue
        seed = TOPIC_SEED_QUERIES.get(topic, text)
        hits = await _search_memory_hits(user_id, seed, top_k=15, threshold=threshold)
        hits += await _search_memory_hits(user_id, text, top_k=8, threshold=0.55)
        ids = []
        for h in hits:
            hid = h.get("id")
            if hid is None or hid in seen_ids:
                continue
            if _topic_key(h.get("text") or "") != topic:
                continue
            ids.append(hid)
            seen_ids.add(hid)
        n = await _delete_ids(ids)
        deleted += n
    if deleted:
        logger.info("memory_replace | user=%s deleted=%d", user_id, deleted)
    return deleted


async def _search_memory_hits(
    user_id: str, query: str, top_k: int = 5, threshold: float = 0.55
) -> list[dict]:
    if not user_id or not query or (not query.strip()):
        return []
    await asyncio.to_thread(milvus_wrapper.create_user_memory_collection, MEMORY_COLLECTION)
    emb = await _embed(query)
    if not emb:
        return []
    filt = f'user_id == "{_escape_user_id(user_id)}"'
    hits = await asyncio.to_thread(
        milvus_wrapper.dense_search_hits,
        MEMORY_COLLECTION,
        emb,
        top_k=top_k,
        filter_expr=filt,
        output_fields=["text", "memory_type"],
    )
    kept = []
    for h in hits:
        if h.get("id") is None:
            continue
        if float(h.get("score") or 0) < threshold:
            continue
        text = h.get("text") or ""
        if _is_noise_memory_text(text):
            continue
        kept.append(h)
    return kept


async def delete_user_memories_by_query(user_id: str, query: str, threshold: float = 0.55) -> int:
    topic = _topic_key(query)
    removed = 0
    for item in await asyncio.to_thread(list_preferences, user_id):
        if (topic and item["topic"] == topic) or (
            not topic and _normalize_memory_text(query) in _normalize_memory_text(item["text"])
        ):
            removed += await asyncio.to_thread(delete_preference, user_id, item["topic"])
    hits = await _search_memory_hits(user_id, query, top_k=8, threshold=threshold)
    ids = [h["id"] for h in hits if h.get("id") is not None]
    if not ids:
        logger.info("memory_delete | user=%s matched=0 query=%s", user_id, query[:40])
        return removed
    n = await _delete_ids(ids)
    if n:
        logger.info("memory_delete | user=%s deleted=%d ids=%s", user_id, n, ids)
    return n + removed


async def search_user_memory(
    user_id: str, query: str, top_k: int = DEFAULT_TOP_K, threshold: float = DEFAULT_THRESHOLD
) -> list[str]:
    """按用户隔离检索长期记忆，返回文本列表（去重并滤噪声）。"""
    if not user_id or not query or (not query.strip()):
        return []
    preferences = await asyncio.to_thread(list_preferences, user_id)
    topic = _topic_key(query)
    current = [p["text"] for p in preferences if not topic or p["topic"] == topic]
    if current:
        return ["[preference] " + t for t in current[:top_k]]
    try:
        await asyncio.to_thread(milvus_wrapper.create_user_memory_collection, MEMORY_COLLECTION)
        emb = await _embed(query)
        if not emb:
            return []
        filt = f'user_id == "{_escape_user_id(user_id)}" and memory_type == "fact"'
        hits = await asyncio.to_thread(
            milvus_wrapper.dense_search,
            MEMORY_COLLECTION,
            emb,
            top_k=max(top_k * 3, top_k),
            filter_expr=filt,
            output_fields=["text", "memory_type"],
        )
        scored = []
        for t, dist in hits:
            if not t or dist is None or float(dist) < threshold:
                continue
            plain = _strip_type_prefix(t)
            if _is_noise_memory_text(plain):
                continue
            scored.append((t, float(dist)))
        texts = _collapse_topic_conflicts(scored)[:top_k]
        logger.info("search_user_memory | user=%s raw=%d kept=%d", user_id, len(hits), len(texts))
        return texts
    except Exception as e:
        logger.error("search_user_memory 失败 user=%s: %s", user_id, e)
        return []


async def _already_has_similar(user_id: str, text: str) -> bool:
    existing = await search_user_memory(user_id, text, top_k=3, threshold=0.88)
    norm = _normalize_memory_text(text)
    for e in existing:
        plain = _strip_type_prefix(e)
        pnorm = _normalize_memory_text(plain)
        if pnorm == norm or (norm and norm in pnorm):
            return True
    return False


async def add_user_memories(user_id: str, items: list[dict]) -> int:
    """写入多条记忆；跳过重复与噪声。"""
    if not user_id or not items:
        return 0
    rows = _filter_items(items)
    if not rows:
        return 0
    preference_rows = [
        row for row in rows if row.get("type", row.get("memory_type")) == "preference"
    ]
    for row in preference_rows:
        await asyncio.to_thread(set_preference, user_id, row["text"])
    rows = [row for row in rows if row not in preference_rows]
    if not rows:
        return len(preference_rows)
    try:
        await asyncio.to_thread(milvus_wrapper.create_user_memory_collection, MEMORY_COLLECTION)
        data = []
        for r in rows:
            mem_type = (r.get("memory_type") or r.get("type") or "fact").strip().lower()
            text = (r.get("text") or "").strip()
            if mem_type not in VALID_TYPES or not text:
                continue
            if await _already_has_similar(user_id, text):
                logger.info("跳过重复记忆: %s", text[:40])
                continue
            emb = await _embed(text)
            if emb is None:
                continue
            data.append(
                {"user_id": user_id, "memory_type": mem_type, "text": text, "embedding": emb}
            )
        if not data:
            return len(preference_rows)
        res = await asyncio.to_thread(
            milvus_wrapper.client.insert, collection_name=MEMORY_COLLECTION, data=data
        )
        count = int(res.get("insert_count", len(data)))
        logger.info("add_user_memories | user=%s count=%d", user_id, count)
        return count + len(preference_rows)
    except Exception as e:
        logger.error("add_user_memories 失败 user=%s: %s", user_id, e)
        return 0


async def extract_and_save_memories(user_id: str, user_msg: str, assistant_msg: str) -> int:
    if not user_id or not user_msg or (not assistant_msg):
        return 0
    if "正在为您转接" in (assistant_msg or ""):
        logger.info("extract_skip | reason=transfer user=%s", user_id)
        return 0
    if is_memory_delete(user_msg):
        n = await delete_user_memories_by_query(user_id, user_msg, threshold=0.5)
        logger.info("extract_done | mode=delete user=%s deleted=%d", user_id, n)
        return n
    want_extract = _should_attempt_extract(user_msg) or is_memory_update(user_msg)
    if not want_extract:
        logger.info("extract_skip | reason=no_trigger user=%s msg=%s", user_id, user_msg[:40])
        return 0
    logger.info("extract_attempt | user=%s msg=%s", user_id, user_msg[:50])
    prompt = EXTRACT_PROMPT.format(
        user_msg=user_msg.strip()[:800], assistant_msg=(assistant_msg or "").strip()[:800]
    )
    try:
        resp = await get_openai_client().chat.completions.create(
            model=CHAT_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0
        )
        raw = resp.choices[0].message.content or ""
        parsed = _parse_extract_output(raw)
        items = _filter_items(parsed)
        logger.info(
            "extract_result | user=%s parsed=%d kept=%d raw=%s",
            user_id,
            len(parsed),
            len(items),
            (raw or "").replace("\n", " ")[:120],
        )
        if not items:
            return 0
        facts = [item for item in items if item.get("type") == "fact"]
        if facts:
            await _replace_related_memories(user_id, facts, threshold=0.4)
        n = await add_user_memories(user_id, items)
        logger.info("extract_done | user=%s inserted=%d", user_id, n)
        return n
    except Exception as e:
        logger.warning("extract_and_save_memories 失败: %s", e)
        return 0
