"""
本地 BGE-M3 向量化，供 RAG / 文档入库 / 长期记忆共用。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import List, Optional, Tuple

# Windows + Anaconda 下常见 OpenMP 重复加载，避免进程直接退出
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from backend.app.core.config import BGE_M3_MODEL_PATH, EMBEDDING_DIM

logger = logging.getLogger(__name__)

# ("bge" | "st", model_instance)
_model: Optional[Tuple[str, object]] = None
_model_lock = threading.Lock()


def get_embedding_dim() -> int:
    return EMBEDDING_DIM


def _load_model_unlocked() -> Tuple[str, object]:
    global _model
    if _model is not None:
        return _model

    path = BGE_M3_MODEL_PATH
    logger.info("加载本地 BGE-M3: %s", path)

    try:
        from FlagEmbedding import BGEM3FlagModel

        model = BGEM3FlagModel(path, use_fp16=False)
        _model = ("bge", model)
        logger.info("BGE-M3 已用 FlagEmbedding 加载")
        return _model
    except Exception as e:
        logger.warning("FlagEmbedding 加载失败，改用 sentence-transformers: %s", e)

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(path)
    _model = ("st", model)
    logger.info("BGE-M3 已用 sentence-transformers 加载")
    return _model


def _load_model() -> Tuple[str, object]:
    with _model_lock:
        return _load_model_unlocked()


def _to_list(vec) -> List[float]:
    if hasattr(vec, "tolist"):
        return [float(x) for x in vec.tolist()]
    return [float(x) for x in vec]


def embed_texts(texts: List[str]) -> List[List[float]]:
    """同步批量向量化。"""
    if not texts:
        return []
    kind, model = _load_model()
    if kind == "bge":
        out = model.encode(
            texts,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        vecs = out["dense_vecs"]
        return [_to_list(v) for v in vecs]

    vecs = model.encode(texts, normalize_embeddings=True)
    return [_to_list(v) for v in vecs]


def embed_text(text: str) -> Optional[List[float]]:
    if not text or not str(text).strip():
        return None
    return embed_texts([str(text).strip()])[0]


async def aembed_texts(texts: List[str]) -> List[List[float]]:
    """异步批量向量化（线程池，避免阻塞事件循环）。"""
    return await asyncio.to_thread(embed_texts, texts)


async def aembed_text(text: str) -> Optional[List[float]]:
    if not text or not str(text).strip():
        return None
    vecs = await aembed_texts([str(text).strip()])
    return vecs[0] if vecs else None
