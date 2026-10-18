"""HTTP 与 SSE 适配层；只把 generate 节点的模型输出发送给客户端。"""

import json
import logging
import uuid
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from backend.app.api.dependencies import verify_token
from backend.app.api.schemas import ChatRequest, ChatResponse
from backend.app.agent.graph import build_graph
from backend.app.memory.long_term import extract_and_save_memories
from backend.app.memory.session import SessionManager

router = APIRouter(tags=["Chat"], dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)
FALLBACK = "抱歉，系统繁忙，请稍后再试或转人工客服。"


async def prepare_state(req: ChatRequest, sid: str):
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


async def persist(req, sid, result, reply):
    await SessionManager.save_history(sid, result["messages"], req.user_id)
    try:
        await extract_and_save_memories(req.user_id, req.message, reply)
    except Exception:
        logger.exception("长期记忆写入失败")


def sse(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())
    async with SessionManager.lock(sid, req.user_id):
        try:
            result = await build_graph().ainvoke(await prepare_state(req, sid))
            reply = result["messages"][-1]["content"]
            await persist(req, sid, result, reply)
            return ChatResponse(
                reply=reply,
                session_id=sid,
                intents=result.get("intents", []),
                memory_hits=result.get("memory_hits", []),
            )
        except Exception:
            logger.exception("对话处理失败 session=%s", sid)
            return ChatResponse(reply=FALLBACK, session_id=sid, degraded=True)


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())

    async def events():
        async with SessionManager.lock(sid, req.user_id):
            try:
                state = await prepare_state(req, sid)
                final_state = None
                sent = []
                async for event in build_graph().astream_events(state, version="v2"):
                    if event.get("event") == "on_chat_model_stream" and "response" in event.get(
                        "tags", []
                    ):
                        chunk = event.get("data", {}).get("chunk")
                        content = getattr(chunk, "content", "")
                        if isinstance(content, str) and content:
                            sent.append(content)
                            yield sse({"type": "token", "content": content})
                    elif event.get("event") == "on_chain_end" and event.get("name") == "LangGraph":
                        final_state = event["data"].get("output")
                if not final_state:
                    raise RuntimeError("Agent 未返回最终状态")
                reply = final_state["messages"][-1]["content"]
                if not sent:
                    yield sse({"type": "token", "content": reply})
                await persist(req, sid, final_state, reply)
                yield sse(
                    {
                        "type": "done",
                        "session_id": sid,
                        "reply": reply,
                        "intents": final_state.get("intents", []),
                        "memory_hits": final_state.get("memory_hits", []),
                    }
                )
            except Exception:
                logger.exception("流式对话失败 session=%s", sid)
                yield sse({"type": "error", "content": FALLBACK, "session_id": sid})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
