"""认证后的图片代理：只读取联网工具实际登记的资产，不提供任意URL代理。"""

import asyncio
import io
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError

from backend.app.api.dependencies import verify_token
from backend.app.core.config import DATA_DIR
from backend.app.infrastructure.store import store
from backend.app.tools.http import fetch_public

router = APIRouter(tags=["Product media"], dependencies=[Depends(verify_token)])


@router.get("/media/{identifier}")
async def product_image(identifier: str):
    if not re.fullmatch(r"[a-f0-9]{64}", identifier):
        raise HTTPException(404, "图片不存在")
    with store.connect() as db:
        asset = db.execute("SELECT * FROM web_assets WHERE id=?", (identifier,)).fetchone()
    if not asset:
        raise HTTPException(404, "图片尚未由联网工具核验")
    cache = DATA_DIR / "web/images" / identifier
    if cache.exists() and time.time() - cache.stat().st_mtime < 3600:
        raw = await asyncio.to_thread(cache.read_bytes)
    else:
        try:
            _, headers, raw = await fetch_public(
                asset["url"], limit=5_000_000, accept="image/avif,image/webp,image/png,image/jpeg"
            )
            if not headers.get("content-type", "").lower().startswith("image/"):
                raise ValueError("未返回图片")
        except Exception as exc:
            raise HTTPException(502, "来源图片暂不可用") from exc
    try:
        image = Image.open(io.BytesIO(raw))
        if (
            image.format not in {"JPEG", "PNG", "WEBP", "AVIF"}
            or min(image.size) < 120
            or max(image.size) > 10000
            or image.width * image.height > 25_000_000
        ):
            raise ValueError("图片格式或尺寸不适合商品展示")
        content_type = Image.MIME.get(image.format, "image/jpeg")
        image.verify()
    except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "未找到有效商品图片") from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists() or time.time() - cache.stat().st_mtime >= 3600:
        import uuid

        temporary = cache.with_suffix("." + uuid.uuid4().hex + ".tmp")
        await asyncio.to_thread(temporary.write_bytes, raw)
        await asyncio.to_thread(temporary.replace, cache)
    return Response(
        content=raw,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        },
    )
