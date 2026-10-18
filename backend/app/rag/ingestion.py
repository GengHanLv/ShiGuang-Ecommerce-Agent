"""
解析上传的文档（PDF、DOCX、TXT），分块，生成向量并插入 Milvus。
"""

import asyncio
import logging
from pathlib import Path
from typing import List

import docx
import pypdf


from backend.app.infrastructure.embeddings import aembed_texts
from backend.app.infrastructure.milvus import milvus_wrapper

logger = logging.getLogger(__name__)


EMBED_BATCH = 64


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """按句子聚合分块，尽量保持语义完整。"""
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("overlap 必须非负且小于 chunk_size")
    text = (text or "").strip()
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
    return "\n".join(para.text for para in doc.paragraphs if para.text)


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


async def process_document(file_path: str, collection_name: str) -> int:
    """主入口：提取文本，分块，向量化，插入 Milvus。返回插入条数。"""
    text = await asyncio.to_thread(extract_text, file_path)
    if not text.strip():
        logger.warning("文件 %s 内容为空，跳过", file_path)
        return 0

    texts = split_text(text, chunk_size=500, overlap=50)
    if not texts:
        return 0

    # 确保集合存在
    await asyncio.to_thread(milvus_wrapper.create_collection, collection_name)

    count = 0
    for offset in range(0, len(texts), EMBED_BATCH):
        batch = texts[offset : offset + EMBED_BATCH]
        vectors = await aembed_texts(batch)
        if len(vectors) != len(batch):
            raise RuntimeError("向量数量与分块数量不一致")
        data = [{"text": content, "embedding": vector} for content, vector in zip(batch, vectors)]
        result = await asyncio.to_thread(
            milvus_wrapper.client.insert, collection_name=collection_name, data=data
        )
        count += int(result.get("insert_count", len(data)))
    logger.info("已向 %s 插入 %s 个片段", collection_name, count)
    return count
