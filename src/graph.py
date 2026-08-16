"""
LangGraph 状态图，实现多意图识别与并行处理。
"""
import asyncio
import logging
import operator
from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from config import CHAT_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from long_term_memory import search_user_memory
from memory_signals import (
    FAQ_KEYWORDS,
    ORDER_KEYWORDS,
    TRANSFER_KEYWORDS,
    extract_order_id,
    has_soft_business_signal,
    is_order_lookup_intent,
    is_preference_query,
    is_preference_utterance,
    is_shipping_policy_question,
    is_stating_new_preference,
    should_inject_memory,
)
from rag_tool import DEFAULT_THRESHOLD, search_knowledge
from tools import query_order

llm = ChatOpenAI(
    model=CHAT_MODEL,
    api_key=OPENAI_API_KEY,
    temperature=0,
    base_url=OPENAI_BASE_URL,
)
logger = logging.getLogger(__name__)

VALID_INTENTS = {"order_query", "knowledge", "transfer_human", "chitchat"}

SYSTEM_PROMPT = """你是电商智能客服。
优先使用参考信息中的订单事实和知识库，禁止编造物流、价格、库存、送达时间，以及资料未写明的规格/功能。
优先级：订单数据 > FAQ/商品知识 > 用户长期记忆 > 闲聊。
长期记忆只是收货偏好等备注：与当前问题相关再融入，不要当开场白，不要据此编造预计送达。
有「订单号=」或「共 N 条订单」时直接播报库中状态，禁止再索要订单号。
资料未写明的功能禁止说支持或不支持，应说明暂无法确认。
无订单/知识结果时不要提查单失败或索要订单号。
陈述新偏好时只确认本轮；询问已记偏好时根据长期记忆回答。
语气简洁，多问题分段，不要泄露其他用户信息。

【参考信息】
{context}
"""


class AgentState(TypedDict):
    messages: Annotated[List[dict], operator.add]
    intents: List[str]
    tool_results: List[str]
    memory_hits: List[str]
    user_id: str
    session_id: str
    order_id: Optional[int]


def _wants_transfer(msg: str) -> bool:
    return any(kw in msg for kw in TRANSFER_KEYWORDS)


async def recall_memory(state: AgentState):
    msg = state["messages"][-1]["content"]
    user_id = state.get("user_id") or ""
    hits = await search_user_memory(user_id, msg)
    logger.info("recall_memory | user=%s hits=%d", user_id, len(hits))
    return {"memory_hits": hits}


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
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
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


async def execute_tools(state: AgentState):
    intents = state.get("intents") or []
    msg = state["messages"][-1]["content"]
    order_id = state.get("order_id")
    tasks = []
    labels = []

    if "order_query" in intents:
        tasks.append(query_order(state["user_id"], order_id=order_id))
        labels.append("order")
    if "knowledge" in intents:
        tasks.append(search_knowledge(msg, "faq", threshold=DEFAULT_THRESHOLD))
        labels.append("faq")
        tasks.append(search_knowledge(msg, "product_knowledge", threshold=DEFAULT_THRESHOLD))
        labels.append("product")
    if "transfer_human" in intents:
        tasks.append(asyncio.sleep(0, result="【转人工】已记录转接请求，请稍候人工客服接入。"))
        labels.append("transfer")

    if not tasks:
        return {"tool_results": []}

    results = await asyncio.gather(*tasks, return_exceptions=True)
    tool_results = []
    for label, r in zip(labels, results):
        if isinstance(r, Exception):
            logger.error("工具 %s 失败: %s", label, r)
            tool_results.append(f"【{label}】查询失败，请稍后重试")
        elif r:
            tool_results.append(f"【{label}】{r}")

    logger.info("execute_tools | results_count=%d", len(tool_results))
    return {"tool_results": tool_results}


def _to_lc_messages(history: List[dict]):
    out = []
    for m in history:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def _has_order_facts(tool_results: List[str]) -> bool:
    text = "\n".join(tool_results or [])
    if "订单查询失败" in text or "未找到用户" in text or "缺少用户标识" in text:
        return False
    return ("订单号=" in text) or ("共 " in text and "条订单" in text)


def _has_knowledge_bits(tool_results: List[str]) -> bool:
    text = "\n".join(tool_results or [])
    return ("【faq】" in text) or ("【product】" in text)


async def generate(state: AgentState):
    intents = state.get("intents") or []
    has_transfer = "transfer_human" in intents
    has_business = "order_query" in intents or "knowledge" in intents

    if has_transfer and not has_business:
        reply = "正在为您转接人工客服，请稍候..."
        logger.info("generate | transfer_human 固定话术")
        return {"messages": [{"role": "assistant", "content": reply}]}

    tool_results = state.get("tool_results") or []
    memory_hits = state.get("memory_hits") or []
    msg = state["messages"][-1]["content"]
    stating_new = is_stating_new_preference(msg)
    inject_memory = should_inject_memory(msg, bool(memory_hits))

    parts = []
    if tool_results:
        parts.append("\n".join(tool_results))
    if inject_memory:
        parts.append("【用户长期记忆】\n" + "\n".join(f"- {m}" for m in memory_hits))
    context = "\n".join(parts) if parts else "（暂无检索到的业务数据）"
    if has_transfer and has_business:
        context += "\n用户同时要求转人工：先回答业务问题，文末可简短告知将协助转接。"

    system = SYSTEM_PROMPT.format(context=context)
    if (is_preference_utterance(msg) or is_preference_query(msg)) and "order_query" not in intents:
        history_msgs = [HumanMessage(content=msg)]
    else:
        history_msgs = _to_lc_messages(state["messages"])
    messages = [SystemMessage(content=system)] + history_msgs

    extra = None
    if _has_order_facts(tool_results):
        extra = "按订单库结果直接回答当前问题。"
    elif "knowledge" in intents or _has_knowledge_bits(tool_results):
        extra = "只根据参考信息回答；资料未写明的功能不要断定支持或不支持。"
    elif stating_new:
        extra = "确认本轮偏好即可，不要查询订单。"
    elif is_preference_query(msg):
        extra = "根据长期记忆回答偏好。"
    elif not has_business:
        extra = "按闲聊回答即可。"
    if extra:
        messages.append(HumanMessage(content=extra))

    resp = await llm.ainvoke(messages)
    logger.info(
        "generate | reply_len=%d intents=%s inject_memory=%s",
        len(resp.content or ""),
        intents,
        inject_memory,
    )
    return {"messages": [{"role": "assistant", "content": resp.content}]}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("recall_memory", recall_memory)
    graph.add_node("classify", classify_intents)
    graph.add_node("tools", execute_tools)
    graph.add_node("generate", generate)
    graph.set_entry_point("recall_memory")
    graph.add_edge("recall_memory", "classify")
    graph.add_edge("classify", "tools")
    graph.add_edge("tools", "generate")
    graph.add_edge("generate", END)
    return graph.compile()
