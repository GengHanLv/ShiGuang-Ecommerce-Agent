import logging
from typing import List
from backend.app.agent.state import AgentState

logger = logging.getLogger(__name__)

import asyncio
from backend.app.tools.orders import query_order
from backend.app.rag.retriever import search_knowledge, DEFAULT_THRESHOLD


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
