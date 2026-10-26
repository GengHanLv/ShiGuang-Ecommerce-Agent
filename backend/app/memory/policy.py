"""纯规则与记忆清洗：无外部服务依赖。"""

import json
import logging
import re

from backend.app.memory.signals import EXTRACT_TRIGGER, is_preference_query

logger = logging.getLogger(__name__)

VALID_TYPES = {"fact", "preference"}


SKIP_USER_PATTERNS = [
    r"^你好",
    r"^您好",
    r"讲个笑话",
    r"讲笑话",
    r"转人工",
    r"投诉",
    r"找经理",
    r"到哪了",
    r"查一下我的订单",
    r"订单号\s*\d+",
]


NOISE_TEXT_PATTERNS = [
    r"订单号",
    r"已发货",
    r"待付款",
    r"待支付",
    r"已签收",
    r"物流信息",
    r"查物流",
    r"查看物流",
    r"查询订单",
    r"查订单",
    r"问订单",
    r"订单状态",
    r"两个订单",
    r"购买了",
    r"蓝牙耳机",
    r"机械键盘",
    r"喜欢听笑话",
    r"讲笑话",
    r"转人工",
    r"投诉",
    r"退货流程",
    r"怎么退货",
]


def _normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def _strip_type_prefix(text: str) -> str:
    return re.sub(r"^\[(?:fact|preference|summary)\]\s*", "", text or "")


def _dedupe_texts(texts: list[str]) -> list[str]:
    seen = set()
    out = []
    for t in texts:
        key = _normalize_memory_text(_strip_type_prefix(t))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


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


def _topic_key(text: str) -> str | None:
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


def _filter_items(items: list[dict]) -> list[dict]:
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
        if mem_type == "fact" and any(x in text for x in ("查询", "询问", "问了", "本次", "刚才")):
            continue
        key = _normalize_memory_text(text)
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": mem_type, "text": text[:500]})
    return out


def _collapse_topic_conflicts(scored: list[tuple]) -> list[str]:
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


def _parse_extract_output(raw: str) -> list[dict]:
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
