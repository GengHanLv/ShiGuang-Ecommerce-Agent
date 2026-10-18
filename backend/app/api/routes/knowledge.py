"""有界文件上传与知识库概览。"""

import asyncio
import logging
from pathlib import Path
import re
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from backend.app.api.dependencies import verify_token
from backend.app.core.config import DATA_DIR
from backend.app.rag.ingestion import process_document
from backend.app.rag.retriever import invalidate_knowledge_cache
from backend.app.infrastructure.milvus import milvus_wrapper

router = APIRouter(tags=["Knowledge"], dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)
COLLECTIONS = {"product_knowledge": "商品知识", "faq": "常见问题"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def sanitize_filename(filename: str):
    name = re.split(r"[\\/]", filename or "upload.bin")[-1]
    name = re.sub(r"[^\w.\-]+", "_", name).strip("._") or "upload.bin"
    return Path(name).stem[:100] + Path(name).suffix[:20]


@router.post("/upload")
async def upload_doc(file: UploadFile = File(...), collection: str = Form("product_knowledge")):
    if collection not in COLLECTIONS:
        raise HTTPException(400, "collection 仅支持 product_knowledge 或 faq")
    name = sanitize_filename(file.filename)
    if Path(name).suffix.lower() not in {".pdf", ".txt", ".docx"}:
        raise HTTPException(400, "支持 PDF、TXT、DOCX 文件")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件过大，上限 10MB")
    if not content:
        raise HTTPException(400, "文件为空")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{uuid.uuid4().hex}_{name}"
    try:
        await asyncio.to_thread(path.write_bytes, content)
        chunks = await process_document(str(path), collection)
        if chunks == 0:
            raise HTTPException(422, "未提取到文本；扫描 PDF 请先完成 OCR")
        await invalidate_knowledge_cache(collection)
        return {
            "message": f"文档 {name} 已处理并存入 {collection}",
            "chunks": chunks,
            "filename": name,
            "collection": collection,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("知识入库失败")
        raise HTTPException(503, "文档处理失败，请检查模型及 Milvus 连接") from exc
    finally:
        path.unlink(missing_ok=True)


@router.get("/knowledge")
async def knowledge_summary():
    def read():
        client = milvus_wrapper.client
        result = []
        filter_expr = ""
        for name, label in COLLECTIONS.items():
            exists = client.has_collection(name)
            if exists:
                client.load_collection(name)
                stored = int(
                    client.query(collection_name=name, filter="", output_fields=["count(*)"])[0][
                        "count(*)"
                    ]
                )
                count = (
                    int(
                        client.query(
                            collection_name=name, filter=filter_expr, output_fields=["count(*)"]
                        )[0]["count(*)"]
                    )
                    if filter_expr
                    else stored
                )
            else:
                count = stored = 0
            result.append(
                {
                    "name": name,
                    "label": label,
                    "chunks": count,
                    "stored_chunks": stored,
                    "excluded_chunks": stored - count,
                }
            )
        return result

    try:
        return {"collections": await asyncio.to_thread(read)}
    except Exception as exc:
        logger.exception("读取知识库统计失败")
        raise HTTPException(503, "知识库暂不可用") from exc
