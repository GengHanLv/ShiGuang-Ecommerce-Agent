import logging
from typing import List
from backend.app.agent.state import AgentState
from backend.app.memory.signals import (
    TRANSFER_KEYWORDS,
    FAQ_KEYWORDS,
    ORDER_KEYWORDS,
    extract_order_id,
    has_soft_business_signal,
    is_order_lookup_intent,
    is_preference_query,
    is_preference_utterance,
    is_shipping_policy_question,
)

logger = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage
from backend.app.core.models import get_chat_model

VALID_INTENTS = {"order_query", "knowledge", "transfer_human", "chitchat"}


def _wants_transfer(msg: str) -> bool:
    return any(kw in msg for kw in TRANSFER_KEYWORDS)


def _rule_intents(msg: str) -> List[str]:
    found: List[str] = []
    if any(kw in msg for kw in TRANSFER_KEYWORDS):
        found.append("transfer_human")
    if is_shipping_policy_question(msg) or any(kw in msg for kw in FAQ_KEYWORDS):
        found.append("knowledge")
    if is_order_lookup_intent(msg) or any(kw in msg for kw in ORDER_KEYWORDS):
        found.append("order_query")
    return list(dict.fromkeys(found))


def _rule_confident(msg: str, intents: List[str]) -> bool:
    if not intents:
        return False
    s = set(intents)
    if s == {"transfer_human"}:
        return True
    if s == {"order_query"} and is_order_lookup_intent(msg):
        return True
    if s == {"knowledge"} and not has_soft_business_signal(msg):
        return True
    if s == {"order_query", "knowledge"} and is_order_lookup_intent(msg):
        return True
    if s == {"order_query", "transfer_human"} and is_order_lookup_intent(msg):
        return True
    if s == {"knowledge", "transfer_human"}:
        return True
    return False


def _parse_whitelist_intents(raw: str, allow_transfer: bool = True) -> List[str]:
    allowed = {"order_query", "knowledge", "chitchat"}
    if allow_transfer:
        allowed.add("transfer_human")
    out: List[str] = []
    text = (raw or "").replace("，", ",")
    for part in text.split(","):
        name = part.strip()
        if name in allowed and name not in out:
            out.append(name)
    return out


async def _llm_complete_intents(msg: str, rule_intents: List[str]) -> List[str]:
    ruled = ",".join(rule_intents) if rule_intents else "无"
    prompt = (
        "你是电商客服意图分类器。只能从白名单选择意图："
        "order_query, knowledge, transfer_human, chitchat。"
        "禁止输出白名单以外的任何意图或解释。\n"
        f"规则已命中：{ruled}\n"
        "任务：歧义消解、多意图拆解、补全遗漏的次要意图；"
        "若规则已足够可原样输出这些意图。\n"
        "说明：order_query=查/改/取消订单、物流包裹、改收货手机号或地址、换绑、催单；"
        "knowledge=退货政策、FAQ、商品参数、发货时效或包邮政策；"
        "transfer_human=明确要求人工/投诉/找经理；"
        "chitchat=闲聊或仅陈述收货偏好。\n"
        "只输出逗号分隔的意图名。\n"
        f"消息：{msg}"
    )
    try:
        resp = await get_chat_model().ainvoke([HumanMessage(content=prompt)])
        return _parse_whitelist_intents(resp.content or "")
    except Exception as e:
        logger.warning("LLM意图补全失败: %s", e)
        return []


def _post_gate_intents(msg: str, intents: List[str]) -> List[str]:
    cleaned = [i for i in intents if i in VALID_INTENTS]
    cleaned = list(dict.fromkeys(cleaned))

    if "transfer_human" in cleaned and not _wants_transfer(msg):
        cleaned = [i for i in cleaned if i != "transfer_human"]

    if is_shipping_policy_question(msg) and "knowledge" not in cleaned:
        cleaned.append("knowledge")
    if is_shipping_policy_question(msg) and not is_order_lookup_intent(msg):
        cleaned = [i for i in cleaned if i != "order_query"]

    if (
        "order_query" in cleaned
        and is_preference_utterance(msg)
        and not is_order_lookup_intent(msg)
    ):
        cleaned = [i for i in cleaned if i != "order_query"]

    business = [i for i in cleaned if i in {"order_query", "knowledge", "transfer_human"}]
    if business:
        cleaned = [i for i in cleaned if i != "chitchat"]
        cleaned = business

    if not cleaned:
        cleaned = ["chitchat"]
    return cleaned


async def classify_intents(state: AgentState):
    msg = state["messages"][-1]["content"]
    order_id = extract_order_id(msg)

    if is_preference_utterance(msg) or is_preference_query(msg):
        if not is_order_lookup_intent(msg) and not _wants_transfer(msg):
            logger.info("classify_intents | rule命中 preference→chitchat")
            return {"intents": ["chitchat"], "order_id": None}

    rule_hit = _rule_intents(msg)
    if is_order_lookup_intent(msg) and "order_query" not in rule_hit:
        rule_hit.append("order_query")

    if _rule_confident(msg, rule_hit):
        intents = _post_gate_intents(msg, rule_hit)
        logger.info(
            "classify_intents | mode=rule_only intents=%s order_id=%s",
            intents,
            order_id,
        )
        return {"intents": intents, "order_id": order_id}

    llm_hit = await _llm_complete_intents(msg, rule_hit)
    merged = list(dict.fromkeys(rule_hit + llm_hit))
    if not merged and llm_hit:
        merged = llm_hit
    intents = _post_gate_intents(msg, merged)
    logger.info(
        "classify_intents | mode=llm_assist rule=%s llm=%s final=%s order_id=%s",
        rule_hit,
        llm_hit,
        intents,
        order_id,
    )
    return {"intents": intents, "order_id": order_id}
