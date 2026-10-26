"""认证后的聊天入口：持久化任务ID、检查点恢复、幂等历史和独立记忆同步。"""

import asyncio
import hashlib
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.app.agent import journal
from backend.app.agent.graph import build_graph
from backend.app.api.dependencies import verify_token
from backend.app.api.schemas import ChatRequest, ChatResponse
from backend.app.infrastructure.store import store
from backend.app.memory.long_term import extract_and_save_memories
from backend.app.memory.session import SessionManager
from backend.app.tools.documents import list_documents

router = APIRouter(tags=["Chat"])
logger = logging.getLogger(__name__)
FALLBACK = "本次处理暂未完成，可以从任务检查点继续处理。"


async def prepare_state(req, sid):
    history = await SessionManager.get_history(sid, req.user_id)
    return {
        "messages": history + [{"role": "user", "content": req.message}],
        "intents": [],
        "tool_results": [],
        "memory_hits": [],
        "user_id": req.user_id,
        "session_id": sid,
        "order_id": None,
    }


async def persist(req, sid, result, reply, run_id):
    await SessionManager.save_history(sid, result["messages"], req.user_id, run_id=run_id)

    def claim_memory():
        with store.connect() as db:
            result = db.execute(
                "INSERT OR IGNORE INTO memory_events VALUES(?,'processing')", (run_id,)
            )
            return result.rowcount == 1

    if await asyncio.to_thread(claim_memory):
        status = "completed"
        try:
            await extract_and_save_memories(req.user_id, req.message, reply)
        except Exception:
            status = "unconfirmed"
            logger.exception("长期记忆同步未确认")

        def finish_memory():
            with store.connect() as db:
                db.execute("UPDATE memory_events SET status=? WHERE run_id=?", (status, run_id))

        await asyncio.to_thread(finish_memory)


def sse(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def response_documents(state, owner, run_id):
    # 原生查询工具可展示此前保存的文件；所有卡片仍由服务端按所有者读取。
    listed = any(
        getattr(m, "type", "") == "tool"
        and getattr(m, "name", "") == "list_saved_documents"
        and getattr(m, "status", "") != "error"
        for m in state.get("react_messages", [])
    )
    return await asyncio.to_thread(list_documents, owner, None if listed else run_id)


def request_run(req, user):
    if req.user_id and req.user_id != user.id:
        raise HTTPException(403, "不能以其他用户身份访问订单、历史或记忆")
    req.user_id = user.id
    request_id = req.request_id or uuid.uuid4().hex
    # 首次请求尚无session_id时，网络重发仍落到同一个任务。
    sid = (
        req.session_id
        or hashlib.sha256(json.dumps([user.id, request_id]).encode()).hexdigest()[:32]
    )
    return journal.create_run(user.id, sid, request_id, req.message)


async def run_events(row, graph):
    sid = row["session_id"]
    owner = row["user_id"]
    identifier = row["id"]
    config = {"configurable": {"thread_id": identifier}, "recursion_limit": 50}
    yield {"type": "task", "run_id": identifier, "session_id": sid, "request_id": row["request_id"]}
    try:
        async with SessionManager.lock(sid, owner):
            row = await asyncio.to_thread(journal.owned_run, identifier, owner)
            if row["status"] == "completed" and row.get("result"):
                result = json.loads(row["result"])
                yield {"type": "token", "content": result["reply"]}
                yield {"type": "done", **result}
                return
            if not await asyncio.to_thread(journal.retry_allowed, identifier):
                raise HTTPException(409, "存在结果未确认且禁止重试的操作，需要人工核对后处理")
            req = ChatRequest(
                user_id=owner, message=row["question"], session_id=sid, request_id=row["request_id"]
            )
            snapshot = (
                await graph.aget_state(config)
                if callable(getattr(graph, "aget_state", None))
                else None
            )
            final_state = None
            if snapshot and snapshot.values and not snapshot.next:
                # 图已完成但HTTP持久化中断：直接提交已有答案，不重跑模型或工具。
                final_state = snapshot.values
            state = None
            if not snapshot or not snapshot.values:
                state = await prepare_state(req, sid)
                state.update(run_id=identifier, request_id=row["request_id"])
            await asyncio.to_thread(
                journal.update_run, identifier, "running", row.get("stage", "prepare")
            )
            sent = []
            if final_state is None:
                if callable(getattr(graph, "astream_events", None)):
                    async for event in graph.astream_events(
                        state, config=config, version="v2", durability="sync"
                    ):
                        if event.get("event") == "on_chat_model_stream" and "response" in event.get(
                            "tags", []
                        ):
                            chunk = event.get("data", {}).get("chunk")
                            content = getattr(chunk, "content", "")
                            if isinstance(content, str) and content:
                                sent.append(content)
                                yield {"type": "token", "content": content}
                        elif (
                            event.get("event") == "on_chain_end"
                            and event.get("name") == "LangGraph"
                        ):
                            final_state = event["data"].get("output")
                else:
                    final_state = await graph.ainvoke(state, config=config)
            if not final_state:
                raise RuntimeError("未取得图最终状态")
            reply = final_state["messages"][-1]["content"]
            if not sent:
                yield {"type": "token", "content": reply}
            await persist(req, sid, final_state, reply, identifier)
            result = {
                "reply": reply,
                "session_id": sid,
                "run_id": identifier,
                "intents": final_state.get("intents", []),
                "memory_hits": final_state.get("memory_hits", []),
                "tool_trace": final_state.get("trace", []),
                "stop_reason": final_state.get("stop_reason", ""),
                "product_images": final_state.get("product_images", []),
                "documents": await response_documents(final_state, owner, identifier),
                "degraded": False,
            }
            await asyncio.to_thread(
                journal.update_run, identifier, "completed", "completed", result
            )
            yield {"type": "done", **result}
    except asyncio.CancelledError:
        current = await asyncio.to_thread(journal.owned_run, identifier, owner)
        await asyncio.shield(
            asyncio.to_thread(
                journal.update_run,
                identifier,
                "interrupted",
                current["stage"],
                None,
                "client_disconnected",
            )
        )
        raise
    except HTTPException as exc:
        yield {
            "type": "error",
            "content": str(exc.detail),
            "session_id": sid,
            "run_id": identifier,
            "retryable": await asyncio.to_thread(journal.retry_allowed, identifier),
        }
    except Exception as exc:
        logger.exception("任务处理失败 run=%s", identifier)
        current = await asyncio.to_thread(journal.owned_run, identifier, owner)
        await asyncio.to_thread(
            journal.update_run, identifier, "failed", current["stage"], None, type(exc).__name__
        )
        yield {
            "type": "error",
            "content": FALLBACK,
            "session_id": sid,
            "run_id": identifier,
            "retryable": await asyncio.to_thread(journal.retry_allowed, identifier),
        }


def active_graph(request):
    return getattr(request.app.state, "graph", None) or build_graph()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, user=Depends(verify_token)):
    row = await asyncio.to_thread(request_run, req, user)
    final = None
    async for event in run_events(row, active_graph(request)):
        if event["type"] == "done":
            final = event
        elif event["type"] == "error":
            final = {
                "reply": event["content"],
                "session_id": row["session_id"],
                "run_id": row["id"],
                "degraded": True,
                "retryable": event.get("retryable", False),
            }
    return ChatResponse(**{k: v for k, v in final.items() if k != "type"})


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, user=Depends(verify_token)):
    row = await asyncio.to_thread(request_run, req, user)

    async def events():
        async for event in run_events(row, active_graph(request)):
            yield sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks")
def tasks(session_id: str | None = None, user=Depends(verify_token)):
    with store.connect() as db:
        rows = db.execute(
            "SELECT id,session_id,question,status,stage,created,updated FROM runs WHERE user_id=? AND (? IS NULL OR session_id=?) ORDER BY created DESC LIMIT 30",
            (user.id, session_id, session_id),
        ).fetchall()
    return {"tasks": [dict(row) for row in rows]}


@router.get("/tasks/{identifier}")
async def task_status(identifier: str, request: Request, user=Depends(verify_token)):
    row = await asyncio.to_thread(journal.owned_run, identifier, user.id)
    graph = active_graph(request)
    snapshot = await graph.aget_state({"configurable": {"thread_id": identifier}})
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "status": row["status"],
        "stage": row["stage"],
        "next_nodes": list(snapshot.next) if snapshot else [],
        "tools": await asyncio.to_thread(journal.public_tools, identifier),
        "retryable": row["status"] in {"failed", "interrupted", "pending"}
        and await asyncio.to_thread(journal.retry_allowed, identifier),
        "updated": row["updated"],
    }


@router.post("/tasks/{identifier}/resume", response_model=ChatResponse)
async def resume(identifier: str, request: Request, user=Depends(verify_token)):
    row = await asyncio.to_thread(journal.owned_run, identifier, user.id)
    final = None
    async for event in run_events(row, active_graph(request)):
        if event["type"] == "done":
            final = event
        elif event["type"] == "error":
            final = {
                "reply": event["content"],
                "session_id": row["session_id"],
                "run_id": identifier,
                "degraded": True,
                "retryable": event.get("retryable", False),
            }
    return ChatResponse(**{k: v for k, v in final.items() if k != "type"})


@router.get("/sessions/{sid}/history")
async def history(sid: str, user=Depends(verify_token)):
    return {"messages": await SessionManager.get_history(sid, user.id)}
