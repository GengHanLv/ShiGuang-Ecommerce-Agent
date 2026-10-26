import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import text

from backend.app.api.dependencies import verify_token

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/status", dependencies=[Depends(verify_token)])
async def status():
    async def redis_probe():
        from backend.app.infrastructure.redis import get_redis

        client = await get_redis()
        return bool(client and await client.ping())

    async def mysql_probe():
        from backend.app.infrastructure.database import engine

        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True

    async def milvus_probe():
        from backend.app.infrastructure.milvus import milvus_wrapper

        await asyncio.to_thread(milvus_wrapper.list_collections)
        return True

    async def check(name, probe):
        try:
            ok = await asyncio.wait_for(probe(), timeout=10)
            return name, "online" if ok else "offline"
        except Exception:
            return name, "offline"

    services = dict(
        await asyncio.gather(
            *(
                check(n, p)
                for n, p in [
                    ("redis", redis_probe),
                    ("mysql", mysql_probe),
                    ("milvus", milvus_probe),
                ]
            )
        )
    )
    return {
        "status": "ok" if all(s == "online" for s in services.values()) else "degraded",
        "services": services,
    }
