"""
提供对外 HTTP API，支持 JSON / SSE 流式输出、鉴权、降级兜底。
"""
import importlib.util
import json
import re
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from config import API_KEY
from document_loader import process_document
from graph import build_graph
from long_term_memory import extract_and_save_memories
from memory import SessionManager

# 从项目根加载 logger，避免把空的根目录同名模块加入 sys.path
_ROOT = Path(__file__).resolve().parent.parent
_logger_spec = importlib.util.spec_from_file_location(
    "project_logger", _ROOT / "logger.py"
)
_logger_mod = importlib.util.module_from_spec(_logger_spec)
_logger_spec.loader.exec_module(_logger_mod)
logger = _logger_mod.logger

api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

app = FastAPI(
    title="电商智能客服agent",
    version="1.1.0",
)

agent = build_graph()

ALLOWED_UPLOAD_EXT = {".pdf", ".txt", ".docx"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB
DATA_DIR = Path("data")


class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


def verify_token(api_key: str = Depends(api_key_scheme)):
    if not api_key or api_key != API_KEY:
        raise HTTPException(401, "Invalid API Key")


def sanitize_filename(filename: str) -> str:
    """防止路径穿越与危险字符。"""
    name = Path(filename or "upload.bin").name
    name = re.sub(r"[^\w.\u4e00-\u9fff\-]+", "_", name, flags=re.UNICODE)
    name = name.strip("._") or "upload.bin"
    if len(name) > 120:
        stem, ext = Path(name).stem[:100], Path(name).suffix[:20]
        name = f"{stem}{ext}"
    return name


async def _prepare_state(req: ChatRequest) -> tuple[str, dict]:
    sid = req.session_id or str(uuid.uuid4())
    history = await SessionManager.get_history(sid)
    history.append({"role": "user", "content": req.message})
    state = {
        "messages": history,
        "intents": [],
        "tool_results": [],
        "memory_hits": [],
        "user_id": req.user_id,
        "session_id": sid,
        "order_id": None,
    }
    return sid, state


async def _persist_long_term_memory(user_id: str, user_msg: str, reply: str) -> None:
    """对话结束后异步沉淀长期记忆；失败不影响主回复。"""
    try:
        n = await extract_and_save_memories(user_id, user_msg, reply)
        if n:
            logger.info(f"长期记忆已写入 user={user_id} count={n}")
    except Exception as e:
        logger.warning(f"长期记忆写入跳过: {e}")


@app.get("/health")
async def health():
    """基础探活（不暴露敏感信息）。"""
    return {"status": "ok"}


@app.post("/chat")
async def chat(req: ChatRequest, _=Depends(verify_token)):
    sid = req.session_id or str(uuid.uuid4())
    logger.info(f"用户 {req.user_id} 会话 {sid} 消息: {req.message}")
    try:
        sid, state = await _prepare_state(req)
        result = await agent.ainvoke(state)
        reply = result["messages"][-1]["content"]
        await SessionManager.save_history(sid, result["messages"])
        await _persist_long_term_memory(req.user_id, req.message, reply)
        return {
            "reply": reply,
            "session_id": sid,
            "intents": result.get("intents", []),
            "memory_hits": result.get("memory_hits", []),
        }
    except Exception as e:
        logger.error(f"处理失败: {e}")
        return JSONResponse(
            {
                "reply": "抱歉，系统繁忙，请稍后再试或转人工客服。",
                "session_id": sid,
                "intents": [],
            }
        )


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, _=Depends(verify_token)):
    """SSE：推送 LLM token；结束时发送 session_id 与完整 reply。"""
    sid = req.session_id or str(uuid.uuid4())
    logger.info(f"[stream] 用户 {req.user_id} 会话 {sid} 消息: {req.message}")

    async def event_gen():
        try:
            sid_local, state = await _prepare_state(req)
            full_reply = []
            final_state = None

            async for event in agent.astream_events(state, version="v2"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    text = getattr(chunk, "content", None) or ""
                    if text:
                        full_reply.append(text)
                        yield f"data: {json.dumps({'type': 'token', 'content': text}, ensure_ascii=False)}\n\n"
                elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                    final_state = event["data"].get("output")

            # 转人工等未走 LLM 流式时，补发完整回复
            if not full_reply and final_state:
                reply = final_state["messages"][-1]["content"]
                full_reply.append(reply)
                yield f"data: {json.dumps({'type': 'token', 'content': reply}, ensure_ascii=False)}\n\n"

            reply_text = "".join(full_reply)
            messages = (final_state or state)["messages"]
            # 若流式只拿到 token、状态里尚无 assistant，补一条
            if messages and messages[-1].get("role") != "assistant":
                messages = list(messages) + [{"role": "assistant", "content": reply_text}]
            elif final_state:
                messages = final_state["messages"]

            await SessionManager.save_history(sid_local, messages)
            await _persist_long_term_memory(req.user_id, req.message, reply_text)
            yield f"data: {json.dumps({'type': 'done', 'session_id': sid_local, 'reply': reply_text, 'intents': (final_state or {}).get('intents', []), 'memory_hits': (final_state or {}).get('memory_hits', [])}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式处理失败: {e}")
            fallback = "抱歉，系统繁忙，请稍后再试或转人工客服。"
            yield f"data: {json.dumps({'type': 'error', 'content': fallback, 'session_id': sid}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/upload")
async def upload_doc(
    file: UploadFile = File(...),
    collection: str = Form("product_knowledge"),
    _=Depends(verify_token),
):
    """
    文档上传：支持 PDF / TXT / DOCX，分块后写入 Milvus。
    """
    if collection not in {"product_knowledge", "faq"}:
        raise HTTPException(400, "collection 仅支持 product_knowledge 或 faq")

    safe_name = sanitize_filename(file.filename or "")
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "文件过大，上限 10MB")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 加 uuid 前缀避免覆盖
    file_path = DATA_DIR / f"{uuid.uuid4().hex[:8]}_{safe_name}"
    file_path.write_bytes(content)

    try:
        await process_document(str(file_path), collection)
    except Exception as e:
        logger.error(f"文档处理失败: {e}")
        raise HTTPException(500, "文档处理失败") from e

    return {"message": f"文档 {safe_name} 已处理并存入 {collection}"}
