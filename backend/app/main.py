"""启动：python -m uvicorn backend.app.main:app --reload"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import CORS_ORIGINS
from backend.app.core.logging import configure_logging
from backend.app.api.routes import chat, health, knowledge


@asynccontextmanager
async def lifespan(app):
    configure_logging()
    yield
    from backend.app.infrastructure.redis import close_redis
    from backend.app.infrastructure.database import engine
    from backend.app.infrastructure.milvus import milvus_wrapper
    from backend.app.core.models import get_openai_client

    await close_redis()
    await engine.dispose()
    milvus_wrapper.close()
    if get_openai_client.cache_info().currsize:
        await get_openai_client().close()
        get_openai_client.cache_clear()


app = FastAPI(title="拾光 · 电商智能客服", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)
for router in [health.router, chat.router, knowledge.router]:
    app.include_router(router)
