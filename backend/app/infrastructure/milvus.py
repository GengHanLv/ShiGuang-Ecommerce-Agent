"""Milvus 适配器：延迟连接，统一索引与结果格式，用户过滤始终保留。"""

import logging
import re
import threading
from typing import List
from pymilvus import DataType, MilvusClient
from backend.app.core.config import EMBEDDING_DIM, MILVUS_HOST, MILVUS_PORT

logger = logging.getLogger(__name__)


def _tokenize_query(query: str) -> List[str]:
    """简易中英关键词：连续中文块、英文数字词，并对长中文补二字切分。"""
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", query.lower())
    extras: List[str] = []
    for p in parts:
        if re.fullmatch(r"[\u4e00-\u9fff]+", p) and len(p) >= 4:
            for i in range(len(p) - 1):
                extras.append(p[i : i + 2])
    return list(dict.fromkeys(parts + extras))


class MilvusWrapper:
    def __init__(self):
        self._client = None
        self._lock = threading.Lock()

    @property
    def client(self):
        with self._lock:
            if self._client is None:
                self._client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}", timeout=8)
            return self._client

    def close(self):
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def list_collections(self):
        return self.client.list_collections()

    def _create(self, name: str, dim: int | None, memory: bool):
        client = self.client
        with self._lock:
            if not client.has_collection(name):
                schema = client.create_schema(auto_id=True)
                schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
                if memory:
                    schema.add_field("user_id", DataType.VARCHAR, max_length=64)
                    schema.add_field("memory_type", DataType.VARCHAR, max_length=32)
                schema.add_field("text", DataType.VARCHAR, max_length=65535)
                schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim or EMBEDDING_DIM)
                client.create_collection(name, schema=schema)
            if not client.list_indexes(name):
                params = client.prepare_index_params()
                params.add_index(
                    field_name="embedding",
                    index_type="IVF_FLAT",
                    metric_type="COSINE",
                    params={"nlist": 128},
                )
                client.create_index(collection_name=name, index_params=params)
            client.load_collection(name)

    def create_collection(self, name: str, dim: int | None = None):
        self._create(name, dim, memory=False)

    def create_user_memory_collection(self, name: str = "user_memory", dim: int | None = None):
        self._create(name, dim, memory=True)

    def ensure_loaded(self, name: str):
        self.client.load_collection(name)

    def dense_search_hits(self, collection, emb, top_k=5, filter_expr=None, output_fields=None):
        fields = list(dict.fromkeys(["id"] + (output_fields or ["text", "memory_type"])))
        self.ensure_loaded(collection)
        # Do not retry without filter: a user-memory query must always stay isolated.
        results = self.client.search(
            collection_name=collection,
            data=[emb],
            limit=top_k,
            output_fields=fields,
            filter=filter_expr or "",
            search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
        )
        hits = []
        for row in results[0] if results else []:
            entity = row.get("entity") or {}
            hits.append(
                {
                    "id": row.get("id", entity.get("id")),
                    "text": entity.get("text", ""),
                    "memory_type": entity.get("memory_type", ""),
                    "score": float(row.get("distance", 0)),
                }
            )
        return hits

    def dense_search(self, collection, emb, top_k=5, filter_expr=None, output_fields=None):
        hits = self.dense_search_hits(
            collection, emb, top_k, filter_expr, output_fields or ["text"]
        )
        return [
            (
                f"[{hit['memory_type']}] {hit['text']}" if hit["memory_type"] else hit["text"],
                hit["score"],
            )
            for hit in hits
        ]

    def hybrid_search(self, collection, query_text, dense_emb, top_k=5, *, filter_expr=None):
        """稠密候选加关键词重排；分数为排序分数，而非纯余弦相似度。"""
        candidates = self.dense_search(
            collection, dense_emb, max(top_k * 3, top_k), filter_expr=filter_expr
        )
        tokens = _tokenize_query(query_text or "")
        ranked = [
            (text, score + 0.3 * sum(token in text.lower() for token in tokens))
            for text, score in candidates
        ]
        return sorted(ranked, key=lambda item: item[1], reverse=True)[:top_k]


milvus_wrapper = MilvusWrapper()
