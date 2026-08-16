"""
用户级长期记忆（重要事实 / 偏好 / 历史总结），存入 Milvus，检索增强 Prompt。
"""
import json
import logging
import re
from typing import List, Optional

from openai import AsyncOpenAI

from config import CHAT_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from embeddings import aembed_text
from init_milvus import milvus_wrapper
from memory_signals import (
    EXTRACT_TRIGGER,
    is_memory_delete,
    is_memory_update,
    is_preference_query,
)

logger = logging.getLogger(__name__)

MEMORY_COLLECTION = "user_memory"
DEFAULT_TOP_K = 3
DEFAULT_THRESHOLD = 0.45
VALID_TYPES = {"fact", "preference"}

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

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

SKIP_USER_PATTERNS = [
    r"^你好", r"^您好", r"讲个笑话", r"讲笑话", r"转人工", r"投诉",
    r"找经理", r"到哪了", r"查一下我的订单", r"订单号\s*\d+",
]

NOISE_TEXT_PATTERNS = [
    r"订单号", r"已发货", r"待付款", r"待支付", r"已签收",
    r"物流信息", r"查物流", r"查看物流",
    r"查询订单", r"查订单", r"问订单", r"订单状态", r"两个订单",
    r"购买了", r"蓝牙耳机", r"机械键盘",
    r"喜欢听笑话", r"讲笑话", r"转人工", r"投诉",
    r"退货流程", r"怎么退货",
]

TOPIC_SEED_QUERIES = {
    "phone_notify": "快递到货电话通知偏好",
    "recv_time": "收货时间早晚偏好",
    "express_co": "指定快递公司偏好",
}


def _escape_user_id(user_id: str) -> str:
    return user_id.replace("\\", "\\\\").replace('"', '\\"')


async def _embed(text: str) -> Optional[list]:
    return await aembed_text(text)

# 去空白，小写，便于去重操作
def _normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())

# 去掉检索前的类型前缀，如 [fact] 或 [preference] 或 [summary] 去掉
def _strip_type_prefix(text: str) -> str:
    return re.sub(r"^\[(?:fact|preference|summary)\]\s*", "", text or "")

# 列表按归一化文本去重
def _dedupe_texts(texts: List[str]) -> List[str]:
    seen = set()
    out = []
    for t in texts:
        key = _normalize_memory_text(_strip_type_prefix(t))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out

# 是否命中噪声规则
def _is_noise_memory_text(text: str) -> bool:
    t = text or ""
    return any(re.search(p, t) for p in NOISE_TEXT_PATTERNS)


def _should_attempt_extract(user_msg: str) -> bool:
    msg = (user_msg or "").strip()
    if len(msg) < 4:
        return False
    if is_preference_query(msg):
        return False
    hit_trigger = any(k in msg for k in EXTRACT_TRIGGER)
    if any(re.search(p, msg) for p in SKIP_USER_PATTERNS) and not hit_trigger:
        return False
    if hit_trigger:
        return True
    if re.search(r"以后.*(?:通知|打电话|电话)", msg):
        return True
    if re.search(
        r"(?:打电话|电话通知|通知我).*(?:快递|到货|收货)|(?:快递|到货|到了).*(?:打电话|通知)",
        msg,
    ):
        return True
    return False


def _topic_key(text: str) -> Optional[str]:
    t = _strip_type_prefix(text or "")
    if "打电话" in t or "电话通知" in t:
        return "phone_notify"
    if "电话" in t and any(k in t for k in ("通知", "打给", "来电", "不要", "不用", "不需要")):
        return "phone_notify"
    if any(k in t for k in ("晚上", "早上", "晚间", "白天")) and any(
        k in t for k in ("收货", "查收", "配送", "送货", "签收", "送达", "送到")
    ):
        return "recv_time"
    if any(k in t for k in ("顺丰", "圆通", "中通", "韵达", "指定快递")):
        return "express_co"
    return None


async def _delete_ids(ids: List) -> int:
    ids = [i for i in ids if i is not None]
    if not ids:
        return 0
    try:
        milvus_wrapper.client.delete(
            collection_name=MEMORY_COLLECTION,
            ids=ids,
        )
        return len(ids)
    except Exception as e:
        logger.error("memory_delete ids 失败: %s", e)
        return 0


async def _replace_related_memories(
    user_id: str,
    items: List[dict],
    threshold: float = 0.4,
) -> int:
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
    user_id: str,
    query: str,
    top_k: int = 5,
    threshold: float = 0.55,
) -> List[dict]:
    if not user_id or not query or not query.strip():
        return []
    milvus_wrapper.create_user_memory_collection(MEMORY_COLLECTION)
    emb = await _embed(query)
    if not emb:
        return []
    filt = f'user_id == "{_escape_user_id(user_id)}"'
    hits = milvus_wrapper.dense_search_hits(
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


async def delete_user_memories_by_query(
    user_id: str,
    query: str,
    threshold: float = 0.55,
) -> int:
    hits = await _search_memory_hits(user_id, query, top_k=8, threshold=threshold)
    ids = [h["id"] for h in hits if h.get("id") is not None]
    if not ids:
        logger.info("memory_delete | user=%s matched=0 query=%s", user_id, query[:40])
        return 0
    n = await _delete_ids(ids)
    if n:
        logger.info("memory_delete | user=%s deleted=%d ids=%s", user_id, n, ids)
    return n


def _filter_items(items: List[dict]) -> List[dict]:
    """规则清洗 LLM 抽取结果。"""
    out = []
    seen = set()
    for it in items:
        mem_type = (it.get("type") or "").strip().lower()
        text = (it.get("text") or "").strip()
        if mem_type == "summary":
            # 总结类几乎全是流水账，一律不存
            continue
        if mem_type not in VALID_TYPES or not text:
            continue
        if _is_noise_memory_text(text):
            logger.info("过滤噪声记忆: %s", text[:50])
            continue
        # fact 也要像稳定信息；过短或像过程描述的丢掉
        if mem_type == "fact" and any(
            x in text for x in ("查询", "询问", "问了", "本次", "刚才")
        ):
            continue
        key = _normalize_memory_text(text)
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": mem_type, "text": text[:500]})
    return out


def _collapse_topic_conflicts(scored: List[tuple]) -> List[str]:
    best_by_topic = {}
    others = []
    for text, score in scored:
        topic = _topic_key(text)
        if topic is None:
            others.append(text)
            continue
        prev = best_by_topic.get(topic)
        if prev is None or float(score) > float(prev[1]):
            best_by_topic[topic] = (text, score)
    ordered = [best_by_topic[k][0] for k in best_by_topic]
    return _dedupe_texts(ordered + others)


# 检索
async def search_user_memory(
    user_id: str,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
) -> List[str]:
    """按用户隔离检索长期记忆，返回文本列表（去重并滤噪声）。"""
    if not user_id or not query or not query.strip():
        return []

    try:
        milvus_wrapper.create_user_memory_collection(MEMORY_COLLECTION)
        emb = await _embed(query)
        if not emb:
            return []

        filt = f'user_id == "{_escape_user_id(user_id)}"'
        hits = milvus_wrapper.dense_search(
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
        logger.info(
            "search_user_memory | user=%s raw=%d kept=%d",
            user_id,
            len(hits),
            len(texts),
        )
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


async def add_user_memories(
    user_id: str,
    items: List[dict],
) -> int:
    """写入多条记忆；跳过重复与噪声。"""
    if not user_id or not items:
        return 0

    rows = _filter_items(items)
    if not rows:
        return 0

    try:
        milvus_wrapper.create_user_memory_collection(MEMORY_COLLECTION)
        data = []
        for r in rows:
            # _filter_items 产出 type/text；兼容 memory_type
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
                {
                    "user_id": user_id,
                    "memory_type": mem_type,
                    "text": text,
                    "embedding": emb,
                }
            )
        if not data:
            return 0

        res = milvus_wrapper.client.insert(
            collection_name=MEMORY_COLLECTION,
            data=data,
        )
        count = int(res.get("insert_count", len(data)))
        logger.info("add_user_memories | user=%s count=%d", user_id, count)
        return count
    except Exception as e:
        logger.error("add_user_memories 失败 user=%s: %s", user_id, e)
        return 0

# 解析LLM输出
def _parse_extract_output(raw: str) -> List[dict]:
    text = (raw or "").strip()
    if not text or text.upper() == "NONE":
        return []
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(obj, list):
        return []
    out = []
    for it in obj:
        if not isinstance(it, dict):
            continue
        mem_type = str(it.get("type", "")).strip().lower()
        content = str(it.get("text", "")).strip()
        if mem_type in {"fact", "preference", "summary"} and content:
            out.append({"type": mem_type, "text": content})
    return out

# 对话后的入口
async def extract_and_save_memories(
    user_id: str,
    user_msg: str,
    assistant_msg: str,
) -> int:
    if not user_id or not user_msg or not assistant_msg:
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
        user_msg=user_msg.strip()[:800],
        assistant_msg=(assistant_msg or "").strip()[:800],
    )
    try:
        resp = await ai_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
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

        await _replace_related_memories(user_id, items, threshold=0.4)

        n = await add_user_memories(user_id, items)
        logger.info("extract_done | user=%s inserted=%d", user_id, n)
        return n
    except Exception as e:
        logger.warning("extract_and_save_memories 失败: %s", e)
        return 0
