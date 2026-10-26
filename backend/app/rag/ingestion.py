"""
解析上传的文档（PDF、DOCX、TXT），分块，生成向量并插入 Milvus。
"""

import asyncio
import hashlib
import json
import logging
import re
import weakref
from dataclasses import dataclass
from pathlib import Path

import docx
import pypdf

from backend.app.infrastructure.embeddings import aembed_texts
from backend.app.infrastructure.milvus import milvus_wrapper
from backend.app.rag.catalog import catalog
from backend.app.rag.entities import model_keys
from backend.app.rag.metadata import scalar_values
from backend.app.rag.schema import chunk_id, create_structured, physical_collection, structured

logger = logging.getLogger(__name__)


EMBED_BATCH = 16  # 较小批次降低本地模型峰值内存


def split_text(text: str, chunk_size: int = 1200, overlap: int = 100) -> list[str]:
    """优先保留完整段落/Markdown表格；超长无标点段落才退回有界滑窗。"""
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("overlap 必须非负且小于 chunk_size")
    text = (text or "").strip()
    # PDF/文本常将条件与数值换行排版，先合并再选择分块边界。
    text = re.sub(
        r"((?:开启|关闭|启用|禁用)(?:主动)?降噪[^\n。；]{0,30})\n[ \t]*"
        r"((?:最长|最多|可达|约|单次|播放|聆听|续航|时间|为|达|\s)*\d+(?:\.\d+)?\s*(?:小时|h\b)[^\n。；]*)",
        r"\1：\2",
        text,
        flags=re.I,
    )
    lines = text.splitlines()
    if (
        len(text) > chunk_size
        and len(lines) > 3
        and all("|" in line for line in lines if line.strip())
    ):
        # 长参数表按整行分块并重复表头，状态列与数值留在同一行。
        header = "\n".join(lines[:2]) + "\n"
        if len(header) < chunk_size // 2 and all(
            len(line) + len(header) + 1 <= chunk_size for line in lines[2:]
        ):
            tables, current = [], header
            for line in lines[2:]:
                if len(current) + len(line) + 1 > chunk_size:
                    tables.append(current.strip())
                    current = header
                current += line + "\n"
            if current != header:
                tables.append(current.strip())
            return tables
    paragraphs = re.split(r"\n\s*\n", text)
    if len(paragraphs) > 1:
        chunks = []
        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > chunk_size:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(split_text(paragraph, chunk_size, overlap))
            elif not current or len(current) + 2 + len(paragraph) <= chunk_size:
                current = current + "\n\n" + paragraph if current else paragraph
            else:
                chunks.append(current)
                current = paragraph
        if current:
            chunks.append(current)
        return chunks
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(
                (text.rfind(char, start + chunk_size // 2, end) for char in "。！？\n"), default=-1
            )
            if boundary >= 0:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def extract_text_from_pdf(file_path: str) -> str:
    reader = pypdf.PdfReader(file_path)
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def extract_text_from_docx(file_path: str) -> str:
    doc = docx.Document(file_path)
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    blocks = []
    for element in doc.element.body:
        if element.tag.endswith("}p"):
            value = Paragraph(element, doc).text
            if value:
                blocks.append(value)
        elif element.tag.endswith("}tbl"):
            rows = [
                " | ".join(cell.text.replace("\n", " ") for cell in row.cells)
                for row in Table(element, doc).rows
            ]
            if rows:
                blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def extract_text_from_txt(file_path: str) -> str:
    raw = Path(file_path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract_text(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(file_path)
    if suffix == ".docx":
        return extract_text_from_docx(file_path)
    return extract_text_from_txt(file_path)


@dataclass
class IngestionResult:
    chunks: int
    inserted: int
    reused: bool
    document_id: str


_ingest_locks = weakref.WeakValueDictionary()


async def process_document(
    file_path: str,
    collection_name: str,
    source_name: str | None = None,
    source_metadata: dict | None = None,
) -> IngestionResult:
    """内容寻址、文档状态和失败续传；相同正文重复上传不会产生重复向量。"""
    if collection_name not in {"faq", "product_knowledge"}:
        raise ValueError("不允许写入该集合")
    text = await asyncio.to_thread(extract_text, file_path)
    if not text.strip():
        return IngestionResult(0, 0, False, "")
    # 分块版本计入文档ID：分块策略改变后不会冒用旧任务状态。
    source_metadata = source_metadata or {}
    identifier = hashlib.sha256(
        (
            collection_name
            + "|split-v5-conditions-1200|"
            + json.dumps(source_metadata, sort_keys=True, ensure_ascii=False)
            + text
        ).encode()
    ).hexdigest()
    lock = _ingest_locks.setdefault(identifier, asyncio.Lock())
    async with lock:
        # 在锁内读取首次文件名，避免同时上传同正文的不同文件名产生重复头。
        previous = catalog.job(identifier)
        name = previous["name"] if previous else (source_name or Path(file_path).name)
        # 分商品/章节处理，不能将上一个型号的测试条件带到下一款商品。
        sections = re.split(r"(?m)(?=^【[^\n]+知识｜|^#{1,4} |^EP-\d{3})", text)
        plain = []
        product_heading = ""
        product_conditions = ""
        for section in sections:
            if not section.strip():
                continue
            heading = section.strip().splitlines()[0][:180]
            if model_keys(heading):
                product_heading = heading
                product_conditions = ""
            conditions = "\n".join(
                line
                for line in section.splitlines()
                if re.search(r"测试条件|测量条件|实验条件|在.*音量.*(?:测得|测试)", line)
            )[:350]
            product_conditions = conditions or product_conditions
            conditions = product_conditions
            context = (
                ("商品型号：" + product_heading + "\n" if product_heading else "")
                + "章节标题："
                + heading
                + "\n"
                + ("测试条件摘要：" + conditions + "\n" if conditions else "")
            )
            for chunk in split_text(section, chunk_size=max(300, 1200 - len(context)), overlap=80):
                plain.append(context + chunk)
        texts = [
            f"[document_id:{identifier}] [chunk:{index}]\n上传来源：{name}\n{chunk}"
            for index, chunk in enumerate(plain)
        ]
        catalog.save_job(identifier, collection_name, name, "processing")
        inserted = 0
        try:
            physical = physical_collection(collection_name)
            if structured(collection_name):
                await asyncio.to_thread(create_structured, physical)
            else:
                await asyncio.to_thread(milvus_wrapper.create_collection, collection_name)
            # 实际核对Milvus而非只信任SQLite：外部删除向量后再次上传可自动补齐。
            iterator = await asyncio.to_thread(
                milvus_wrapper.client.query_iterator,
                collection_name=physical,
                filter="text like "
                + json.dumps("[document_id:" + identifier + "]%", ensure_ascii=False),
                output_fields=["text"],
                consistency_level="Strong",
                batch_size=256,
            )
            existing = set()
            try:
                while batch := await asyncio.to_thread(iterator.next):
                    existing.update(r["text"] for r in batch)
            finally:
                await asyncio.to_thread(iterator.close)
            pending = [chunk for chunk in texts if chunk not in existing]
            for offset in range(0, len(pending), EMBED_BATCH):
                batch = pending[offset : offset + EMBED_BATCH]
                vectors = await aembed_texts(batch)
                if len(vectors) != len(batch):
                    raise RuntimeError("向量数量不一致")
                result = await asyncio.to_thread(
                    milvus_wrapper.client.insert,
                    collection_name=physical,
                    data=[
                        {
                            "id": chunk_id(t),
                            "text": t,
                            "embedding": v,
                            **scalar_values(t, source_metadata),
                        }
                        if structured(collection_name)
                        else {"text": t, "embedding": v}
                        for t, v in zip(batch, vectors)
                    ],
                )
                count = int(result.get("insert_count", 0))
                if count != len(batch):
                    raise RuntimeError("写入数量不一致，任务可重试")
                inserted += count
            await asyncio.to_thread(milvus_wrapper.client.flush, collection_name=physical)
            catalog.save_job(identifier, collection_name, name, "completed", len(texts))
            return IngestionResult(len(texts), inserted, not pending, identifier)
        except Exception as exc:
            catalog.save_job(
                identifier, collection_name, name, "failed", inserted, type(exc).__name__
            )
            raise
