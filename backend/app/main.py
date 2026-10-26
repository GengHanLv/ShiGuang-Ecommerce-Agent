"""启动：python -m uvicorn backend.app.main:app --reload"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.app.agent.graph import build_graph
from backend.app.api.routes import (
    auth,
    chat,
    documents,
    health,
    knowledge,
    media,
    orders,
    preferences,
    tools,
)
from backend.app.core.config import CORS_ORIGINS, DATA_DIR
from backend.app.core.logging import configure_logging
from backend.app.security.auth import bootstrap_admin
from backend.app.tools.registry import registry


@asynccontextmanager
async def lifespan(app):
    configure_logging()
    await asyncio.to_thread(bootstrap_admin)
    checkpoint_path = DATA_DIR / "agent/checkpoints.sqlite3"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        app.state.graph = build_graph(saver)
        await registry.reload()
        yield
    from backend.app.core.models import get_openai_client
    from backend.app.infrastructure.database import engine
    from backend.app.infrastructure.milvus import milvus_wrapper
    from backend.app.infrastructure.redis import close_redis

    await close_redis()
    await engine.dispose()
    milvus_wrapper.close()
    if get_openai_client.cache_info().currsize:
        await get_openai_client().close()
        get_openai_client.cache_clear()


app = FastAPI(title="拾光 · 电商智能客服", version="3.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
for router in [
    auth.router,
    health.router,
    chat.router,
    knowledge.router,
    preferences.router,
    media.router,
    tools.router,
    documents.router,
    orders.router,
]:
    app.include_router(router)
