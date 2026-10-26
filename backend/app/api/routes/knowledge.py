"""有界文件上传与知识库概览。"""

import asyncio
import logging
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.app.api.dependencies import require_admin, verify_token
from backend.app.core.config import DATA_DIR
from backend.app.infrastructure.milvus import milvus_wrapper
from backend.app.rag.catalog import catalog
from backend.app.rag.corpus import active_retrieval_filter
from backend.app.rag.ingestion import IngestionResult, process_document
from backend.app.rag.reranker import assess_evidence
from backend.app.rag.retriever import invalidate_knowledge_cache, retrieve
from backend.app.rag.schema import migrate_collections, physical_collection

router = APIRouter(tags=["Knowledge"], dependencies=[Depends(verify_token)])
logger = logging.getLogger(__name__)
COLLECTIONS = {"product_knowledge": "商品知识", "faq": "常见问题"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def sanitize_filename(filename: str):
    name = re.split(r"[\\/]", filename or "upload.bin")[-1]
    name = re.sub(r"[^\w.\-]+", "_", name).strip("._") or "upload.bin"
    return Path(name).stem[:100] + Path(name).suffix[:20]


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload_doc(
    file: UploadFile = File(...),
    collection: str = Form("product_knowledge"),
    source_url: str = Form(""),
    published_at: str = Form(""),
    effective_at: str = Form(""),
    reviewed_at: str = Form(""),
):
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
        dates = {
            key: value
            for key, value in {
                "published_at": published_at,
                "effective_at": effective_at,
                "reviewed_at": reviewed_at,
            }.items()
            if value
        }
        if any(not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value) for value in dates.values()):
            raise HTTPException(422, "来源日期格式需为 YYYY-MM-DD")
        try:
            for value in dates.values():
                date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(422, "来源日期不是有效日期") from exc
        if source_url and (
            urlsplit(source_url).scheme not in {"https", "http"} or urlsplit(source_url).username
        ):
            raise HTTPException(422, "来源网址需为不含凭据的 HTTP(S) 地址")
        extra = {**dates, **({"source_url": source_url} if source_url else {})}
        outcome = await process_document(
            str(path), collection, source_name=name, **({"source_metadata": extra} if extra else {})
        )
        # 兼容旧测试/适配器的整数返回值。
        if isinstance(outcome, int):
            outcome = IngestionResult(outcome, outcome, False, "")
        chunks = outcome.chunks
        if chunks == 0:
            raise HTTPException(422, "未提取到文本；扫描 PDF 请先完成 OCR")
        await invalidate_knowledge_cache(collection)
        return {
            "message": f"文档 {name} 已处理并存入 {collection}",
            "chunks": chunks,
            "filename": name,
            "collection": collection,
            "document_id": outcome.document_id,
            "inserted": outcome.inserted,
            "reused": outcome.reused,
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
        filter_expr = active_retrieval_filter()
        for name, label in COLLECTIONS.items():
            physical = physical_collection(name)
            exists = client.has_collection(physical)
            if exists:
                client.load_collection(physical)
                stored = int(
                    client.query(collection_name=physical, filter="", output_fields=["count(*)"])[
                        0
                    ]["count(*)"]
                )
                count = (
                    int(
                        client.query(
                            collection_name=physical, filter=filter_expr, output_fields=["count(*)"]
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
                    "physical_collection": physical,
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


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    collection: Literal["faq", "product_knowledge"] = "faq"
    platform: Literal["all", "jd", "tmall", "pdd"] = "all"
    top_k: int = Field(default=3, ge=1, le=10)


@router.post("/knowledge/search")
async def search_preview(request: RetrievalRequest):
    """查看型号过滤、混合召回与精排结果；默认LLM精排会调用模型。"""
    try:
        hits = await retrieve(
            request.query, request.collection, request.top_k, platform=request.platform
        )
        return {"hits": hits, "assessment": assess_evidence(request.query, hits)}
    except Exception as exc:
        logger.exception("检索预览失败")
        raise HTTPException(503, "检索暂时不可用") from exc


@router.get("/knowledge/documents", dependencies=[Depends(require_admin)])
async def document_jobs():
    """只返回文档级状态，不暴露本机绝对文件路径和内部异常详情。"""
    return {"documents": await asyncio.to_thread(catalog.jobs)}


@router.post("/knowledge/migrate", dependencies=[Depends(require_admin)])
async def migrate():
    result = await asyncio.to_thread(migrate_collections)
    for name in COLLECTIONS:
        await invalidate_knowledge_cache(name)
    return {"collections": result}
