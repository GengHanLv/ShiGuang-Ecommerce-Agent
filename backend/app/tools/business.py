"""ReAct 工具白名单：业务参数给模型，user_id由InjectedState注入。"""

import asyncio
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from backend.app.memory.long_term import search_user_memory
from backend.app.rag.retriever import search_knowledge
from backend.app.tools.documents import ReportSection, create_report, list_documents
from backend.app.tools.orders import query_order


@tool
async def lookup_order(state: Annotated[dict, InjectedState], order_id: int | None = None) -> str:
    """查询当前登录用户的订单状态，可选指定订单号。不能取消订单、退款或修改地址。"""
    return await query_order(state["user_id"], order_id=order_id)


@tool
async def search_products(
    query: str,
    state: Annotated[dict, InjectedState],
    platform: Literal["all", "jd", "tmall", "pdd"] = "all",
) -> str:
    """检索具体商品型号、规格和功能。指定京东jd、天猫tmall、拼多多pdd，未指定用all。"""
    return await search_knowledge(
        query,
        "product_knowledge",
        platform=platform,
        original_query=state["messages"][-1]["content"],
    )


@tool
async def search_faq(query: str, platform: Literal["all", "jd", "tmall", "pdd"] = "all") -> str:
    """检索退换货、发票、运费等平台规则，保留适用范围与来源。比较多平台时分别查询。"""
    return await search_knowledge(query, "faq", platform=platform)


@tool
async def recall_preferences(query: str, state: Annotated[dict, InjectedState]) -> str:
    """读取当前用户已保存的长期偏好；不能读取其他用户的信息，也不能据此承诺送达。"""
    rows = await search_user_memory(state["user_id"], query)
    return "\n".join(rows) if rows else "暂无相关的已保存偏好"


@tool
async def request_human_service(reason: str = "用户请求人工服务") -> str:
    """说明用户希望人工处理。仅演示意向登记，未连接真人客服，也未创建真实工单。"""
    return "已了解您的人工服务需求；本项目尚未对接真实人工客服，请通过平台官方客服入口联系。"


@tool
async def export_consultation_pdf(
    title: str, sections: list[ReportSection], state: Annotated[dict, InjectedState]
) -> str:
    """用户明确要求保存/导出文档时，将有证据的咨询总结、选购对比或售后准备清单保存为中文PDF。sections含heading/content；不能捏造参数、订单或承诺。返回私有下载文件，不提交售后申请。"""
    question = state["messages"][-1]["content"]
    if not re.search(r"导出|保存|下载|生成.*(?:报告|文档|文件)|pdf", question, re.I):
        raise ValueError("仅在用户明确要求保存或导出时创建文件")
    sources = []
    for message in state.get("react_messages", []):
        if getattr(message, "type", "") != "tool" or getattr(message, "status", "") == "error":
            continue
        if getattr(message, "name", "") not in {
            "search_products",
            "search_faq",
            "fetch_product_page",
        }:
            continue
        try:
            result = json.loads(message.content)
            rows = result.get("evidence", []) if message.name != "fetch_product_page" else [result]
            for row in rows:
                for url in [row.get("source_url", ""), row.get("url", ""), *row.get("urls", [])]:
                    parsed = urlsplit(url)
                    if (
                        parsed.scheme in {"http", "https"}
                        and parsed.hostname
                        and not parsed.username
                    ):
                        sources.append(url)
        except (ValueError, TypeError, AttributeError):
            continue
    result = await asyncio.to_thread(
        create_report,
        state["user_id"],
        state["run_id"],
        title,
        [s.model_dump() for s in sections],
        sources,
    )
    return json.dumps({"document": result, "status": "created"}, ensure_ascii=False)


@tool
async def list_saved_documents(state: Annotated[dict, InjectedState]) -> str:
    """查看当前登录用户最近保存的PDF文档，返回标题和下载信息，不能查看其他用户。"""
    return json.dumps(
        {"documents": await asyncio.to_thread(list_documents, state["user_id"])}, ensure_ascii=False
    )


export_consultation_pdf.metadata = {"read_only": False, "retryable": True}

TOOLS = [
    lookup_order,
    search_products,
    search_faq,
    recall_preferences,
    request_human_service,
    export_consultation_pdf,
    list_saved_documents,
]
TOOL_INTENTS = {
    "lookup_order": "order_query",
    "search_products": "knowledge",
    "search_faq": "knowledge",
    "recall_preferences": "chitchat",
    "request_human_service": "transfer_human",
}
