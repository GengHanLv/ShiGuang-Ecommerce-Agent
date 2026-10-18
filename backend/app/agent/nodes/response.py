import logging
from typing import List
from backend.app.agent.state import AgentState
from backend.app.memory.signals import (
    is_stating_new_preference,
    should_inject_memory,
    is_preference_utterance,
    is_preference_query,
)

logger = logging.getLogger(__name__)

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from backend.app.core.models import get_chat_model
from backend.app.agent.prompts import SYSTEM_PROMPT


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

    resp = await get_chat_model().with_config(tags=["response"]).ainvoke(messages)
    logger.info(
        "generate | reply_len=%d intents=%s inject_memory=%s",
        len(resp.content or ""),
        intents,
        inject_memory,
    )
    return {"messages": [{"role": "assistant", "content": resp.content}]}
