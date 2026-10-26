"""显式ReAct状态图：模型决策 → 工具观察 → 再次决策，最后统一生成答复。"""

import asyncio
import json
import os
import re
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.app.agent import journal
from backend.app.agent.prompts import FINAL_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from backend.app.agent.state import AgentState
from backend.app.core.models import get_chat_model
from backend.app.rag.media import resolve_product_images
from backend.app.tools.business import TOOL_INTENTS, TOOLS
from backend.app.tools.registry import registry

MAX_TOOL_ROUNDS = max(1, min(int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "4")), 8))
MAX_TOOL_CALLS = max(1, min(int(os.getenv("AGENT_MAX_TOOL_CALLS", "8")), 16))
TOOL_TIMEOUT = max(5, min(float(os.getenv("AGENT_TOOL_TIMEOUT", "180")), 240))


def observation_summary(message):
    """只汇总实际工具观察，不读取或暴露模型的内部推理文本。"""
    summary = (
        "工具已返回资料，答复据此整理。"
        if message.status != "error"
        else "读取失败，未作为有效资料。"
    )
    sources = []
    try:
        value = json.loads(message.content)
        if isinstance(value, dict):
            rows = value.get("results", value.get("evidence", []))
            if not isinstance(rows, list):
                rows = []
            if value.get("url"):
                rows = [value, *rows]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = row.get("url") or row.get("source_url", "")
                from urllib.parse import urlsplit

                parsed = urlsplit(url)
                if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
                    sources.append(
                        {"title": str(row.get("title") or parsed.hostname)[:180], "url": url}
                    )
            if message.name == "web_search":
                summary = (
                    f"找到 {len(value.get('results', []))} 条来源；搜索摘要与网页正文分别标注。"
                )
            elif message.name == "fetch_product_page":
                summary = (
                    "页面要求验证或无法读取，保留链接。"
                    if value.get("status") != "ok"
                    else f"已读取页面；{'型号相关' if value.get('model_match') else '型号尚未匹配'}，提取 {len(value.get('images', []))} 张来源图片。"
                )
    except (ValueError, TypeError, AttributeError):
        pass
    if message.name == "lookup_order":
        summary = "按当前登录身份查询订单；模拟数据与真实订单分开标注。"
    return {"summary": summary, "sources": sources[:6]}


async def prepare_react(state: AgentState):
    """每次请求重新构造内部消息，避免将上一轮工具调用残片混入下一轮。"""
    conversation = [
        HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"])
        for m in state["messages"]
        if m.get("role") in {"user", "assistant"}
    ]
    return {
        "react_messages": [SystemMessage(REACT_SYSTEM_PROMPT), *conversation],
        "steps": 0,
        "tool_calls_count": 0,
        "memory_hits": [],
        "intents": [],
        "stop_reason": "",
    }


async def decide(state: AgentState):
    if state.get("run_id"):
        await asyncio.to_thread(journal.update_run, state["run_id"], "running", "decide")
    if state.get("stop_reason") == "tool_timeout":
        return {"stop_reason": "tool_timeout"}
    if state["steps"] >= MAX_TOOL_ROUNDS:
        # 不再向模型绑定工具，下一步进入统一的最终回复节点。
        return {"stop_reason": "tool_round_budget"}
    model = get_chat_model().bind_tools([*TOOLS, *registry.tools])
    response = await model.with_config(tags=["react_decision"]).ainvoke(state["react_messages"])
    return {
        "react_messages": [response],
        "steps": state["steps"] + 1,
        "stop_reason": "answer_ready" if not response.tool_calls else "",
    }


def route_decision(state: AgentState):
    last = state["react_messages"][-1]
    calls = getattr(last, "tool_calls", [])
    if state.get("stop_reason") or not calls:
        return "finalize"
    if state["tool_calls_count"] + len(calls) > MAX_TOOL_CALLS:
        return "finalize"
    return "actions"


async def act(state: AgentState):
    """ToolNode校验参数并注入身份；错误转换成观察，不无过滤重试。"""
    calls = state["react_messages"][-1].tool_calls
    begin = time.perf_counter()
    observations = []
    timeout = False
    available = [*TOOLS, *registry.tools]
    if state.get("run_id"):
        await asyncio.to_thread(journal.update_run, state["run_id"], "running", "actions")
    for call in calls:
        tool = next((t for t in available if t.name == call["name"]), None)
        retryable = bool(tool and (tool.metadata or {}).get("retryable", tool in TOOLS))
        cached = None
        if state.get("run_id"):
            cached = await asyncio.to_thread(
                journal.start_tool,
                state["run_id"],
                call["id"],
                call["name"],
                call["args"],
                retryable,
            )
        if cached:
            observations.append(ToolMessage(**cached))
            continue
        try:
            if tool is None:
                raise ValueError("工具不在允许列表内")
            if (tool.metadata or {}).get("mcp_server"):
                # 联网工具不携带用户身份、会话凭证或私人订单数据。
                encoded = json.dumps(call["args"], ensure_ascii=False)
                if re.search(
                    r"sk-[a-zA-Z0-9_-]{16,}|Bearer\s+|1[3-9]\d{9}|订单(?:号|ID)[：:\s]*\d+|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}",
                    encoded,
                    re.I,
                ):
                    raise ValueError("联网工具仅允许查询公开商品资料，不能发送私人信息或凭证")
                if any(
                    len(state.get(key, "")) > 6 and state[key] in encoded
                    for key in ("user_id", "session_id")
                ):
                    raise ValueError("不得向网络工具发送用户或会话标识")
            for attempt in range(2 if retryable else 1):
                local = {
                    **state,
                    "react_messages": [
                        *state["react_messages"][:-1],
                        state["react_messages"][-1].model_copy(update={"tool_calls": [call]}),
                    ],
                }
                try:
                    output = await asyncio.wait_for(
                        ToolNode(
                            [tool], messages_key="react_messages", handle_tool_errors=True
                        ).ainvoke(local),
                        timeout=TOOL_TIMEOUT,
                    )
                    message = output["react_messages"][0]
                except TimeoutError:
                    timeout = True
                    message = ToolMessage(
                        content="工具超时，当前无法确认结果。",
                        tool_call_id=call["id"],
                        name=call["name"],
                        status="error",
                    )
                transient = message.status == "error" and re.search(
                    r"timeout|temporar|connection|超时|502|503", str(message.content), re.I
                )
                if not transient or attempt == 1 or timeout:
                    break
                if state.get("run_id"):
                    await asyncio.to_thread(
                        journal.finish_tool,
                        state["run_id"],
                        call["id"],
                        {
                            "content": message.content,
                            "tool_call_id": call["id"],
                            "name": call["name"],
                            "status": "error",
                        },
                        False,
                    )
                    await asyncio.to_thread(
                        journal.start_tool,
                        state["run_id"],
                        call["id"],
                        call["name"],
                        call["args"],
                        retryable,
                    )
        except asyncio.CancelledError:
            if state.get("run_id"):
                await asyncio.shield(
                    asyncio.to_thread(
                        journal.finish_tool,
                        state["run_id"],
                        call["id"],
                        {
                            "content": "执行中断；只读操作允许恢复后重试。",
                            "tool_call_id": call["id"],
                            "name": call["name"],
                            "status": "error",
                        },
                        False,
                    )
                )
            raise
        except Exception:
            message = ToolMessage(
                content="工具未能完成读取，请勿假设操作成功。",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
        if state.get("run_id"):
            await asyncio.to_thread(
                journal.finish_tool,
                state["run_id"],
                call["id"],
                {
                    "content": message.content,
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "status": message.status,
                },
                message.status != "error",
            )
        observations.append(message)
    elapsed = round((time.perf_counter() - begin) * 1000)
    intents = list(
        dict.fromkeys(
            state.get("intents", []) + [TOOL_INTENTS.get(c["name"], "chitchat") for c in calls]
        )
    )
    hits = list(state.get("memory_hits", []))
    for message in observations:
        if message.name == "recall_preferences" and message.status != "error":
            hits.append(message.content)
    return {
        "react_messages": observations,
        "tool_calls_count": state["tool_calls_count"] + len(calls),
        "tool_results": [str(m.content) for m in observations],
        "intents": intents,
        "memory_hits": hits,
        "stop_reason": "tool_timeout" if timeout else "",
        "trace": [
            {
                "step": state["steps"],
                "tool": m.name,
                "status": "timeout" if timeout and m.status == "error" else m.status,
                "elapsed_ms": elapsed,
                "result_chars": len(str(m.content)),
                **observation_summary(m),
            }
            for m in observations
        ],
    }


async def timed_act(state: AgentState):
    return await act(state)


async def finalize(state: AgentState):
    """仅此节点打response标签；SSE不会发送规划文本或工具调用参数。"""
    if state.get("run_id"):
        await asyncio.to_thread(journal.update_run, state["run_id"], "running", "generate")
    internal = list(state["react_messages"][1:])
    last = internal[-1] if internal else None
    if isinstance(last, AIMessage) and last.tool_calls:
        # 预算不足时也补齐ToolMessage，避免产生不合法的tool-call对话协议。
        internal += [
            ToolMessage(
                content="工具预算不足，本次未执行此调用。", tool_call_id=c["id"], name=c["name"]
            )
            for c in last.tool_calls
        ]
    messages = [
        SystemMessage(FINAL_SYSTEM_PROMPT),
        *internal,
        # 生成约束属于系统消息，不能伪装成新的用户问题而覆盖真实问题。
        SystemMessage(
            "直接回答用户最近的问题，不复述内部工作流程。"
            "仅将本轮资料支持的事项写作确定事实；品牌规格不证明平台在售，核验日期不是官网发布日期。"
            "首句给实质信息，缺少参数时具体说明缺少什么，不使用模板开场或自我声明。"
        ),
    ]
    response = await get_chat_model().with_config(tags=["response"]).ainvoke(messages)
    return {
        "messages": [{"role": "assistant", "content": response.content}],
        "intents": state.get("intents") or ["chitchat"],
        "stop_reason": state.get("stop_reason") or "tool_call_budget",
    }


async def enrich_media(state: AgentState):
    if state.get("run_id"):
        await asyncio.to_thread(journal.update_run, state["run_id"], "running", "media")
    return {
        "product_images": await resolve_product_images(
            state["react_messages"], state["messages"][-1]["content"], state.get("run_id")
        )
    }


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)
    graph.add_node("prepare", prepare_react)
    graph.add_node("decide", decide)
    graph.add_node("actions", timed_act)
    graph.add_node("generate", finalize)
    graph.add_node("media", enrich_media)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "decide")
    graph.add_conditional_edges(
        "decide", route_decision, {"actions": "actions", "finalize": "generate"}
    )
    graph.add_edge("actions", "decide")
    graph.add_edge("generate", "media")
    graph.add_edge("media", END)
    return graph.compile(checkpointer=checkpointer)
