"""
封装 Milvus 客户端，提供集合管理、索引创建、稠密检索 + 关键词重排。
"""
import logging
import re
from typing import List, Tuple

from pymilvus import DataType, MilvusClient

from config import EMBEDDING_DIM, MILVUS_HOST, MILVUS_PORT

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
        self.client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")

    def create_collection(self, name: str, dim: int | None = None):
        dim = dim if dim is not None else EMBEDDING_DIM
        if self.client.has_collection(name):
            return
        schema = self.client.create_schema(auto_id=True)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("text", DataType.VARCHAR, max_length=65535)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
        self.client.create_collection(name, schema=schema)
        self._ensure_index(name)

    def ensure_loaded(self, name: str) -> None:
        """检索前加载集合，避免 collection not loaded。"""
        try:
            self.client.load_collection(name)
        except Exception as e:
            logger.warning("load_collection(%s) 失败/可忽略: %s", name, e)

    def create_user_memory_collection(self, name: str = "user_memory", dim: int | None = None):
        """用户长期记忆集合：带 user_id / memory_type，检索时按用户过滤。"""
        dim = dim if dim is not None else EMBEDDING_DIM
        if self.client.has_collection(name):
            self.ensure_loaded(name)
            return
        schema = self.client.create_schema(auto_id=True)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("user_id", DataType.VARCHAR, max_length=64)
        schema.add_field("memory_type", DataType.VARCHAR, max_length=32)
        schema.add_field("text", DataType.VARCHAR, max_length=65535)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
        self.client.create_collection(name, schema=schema)
        self._ensure_index(name)
        self.ensure_loaded(name)
        logger.info("已创建长期记忆集合 %s", name)

    def _ensure_index(self, name: str):
        try:
            if hasattr(self.client, "prepare_index_params"):
                index_params = self.client.prepare_index_params()
                index_params.add_index(
                    field_name="embedding",
                    index_type="IVF_FLAT",
                    metric_type="COSINE",
                    params={"nlist": 128},
                )
                self.client.create_index(collection_name=name, index_params=index_params)
                return
        except Exception as e:
            logger.warning("prepare_index_params 失败，尝试旧 API: %s", e)

        try:
            self.client.create_index(
                name,
                index_type="IVF_FLAT",
                metric_type="COSINE",
                params={"nlist": 128},
            )
        except Exception:
            try:
                index_params = {
                    "index_type": "IVF_FLAT",
                    "metric_type": "COSINE",
                    "params": {"nlist": 128},
                }
                self.client.create_index(name, index_params=index_params)
            except Exception as e:
                logger.warning("自动创建索引失败，请在 Attu 中为 %s 建索引: %s", name, e)

    def dense_search(
        self,
        collection: str,
        emb,
        top_k: int = 5,
        filter_expr: str | None = None,
        output_fields: List[str] | None = None,
    ) -> List[Tuple[str, float]]:
        """稠密向量检索，返回 [(text, score), ...]；COSINE 下 score 越大越相似。"""
        fields = output_fields or ["text"]
        self.ensure_loaded(collection)

        def _do_search():
            try:
                kwargs = {
                    "collection_name": collection,
                    "data": [emb],
                    "limit": top_k,
                    "output_fields": fields,
                    "search_params": {"metric_type": "COSINE", "params": {"nprobe": 16}},
                }
                if filter_expr:
                    kwargs["filter"] = filter_expr
                return self.client.search(**kwargs)
            except TypeError:
                try:
                    kwargs = {
                        "collection_name": collection,
                        "data": [emb],
                        "limit": top_k,
                        "output_fields": fields,
                    }
                    if filter_expr:
                        kwargs["filter"] = filter_expr
                    return self.client.search(**kwargs)
                except TypeError:
                    return self.client.search(
                        collection, data=[emb], limit=top_k, output_fields=fields
                    )

        try:
            results = _do_search()
        except Exception as e:
            # 未加载时再 load 重试一次
            if "not loaded" in str(e).lower():
                self.ensure_loaded(collection)
                try:
                    results = _do_search()
                except Exception as e2:
                    logger.error("dense_search 失败: %s", e2)
                    return []
            else:
                logger.error("dense_search 失败: %s", e)
                return []

        hits = []
        if not results:
            return hits
        for row in results[0]:
            entity = row.get("entity") or {}
            text = entity.get("text") or row.get("text") or ""
            mem_type = entity.get("memory_type") or ""
            if mem_type and text:
                text = f"[{mem_type}] {text}"
            dist = row.get("distance", 0.0)
            hits.append((text, float(dist)))
        return hits

    def dense_search_hits(
        self,
        collection: str,
        emb,
        top_k: int = 5,
        filter_expr: str | None = None,
        output_fields: List[str] | None = None,
    ) -> List[dict]:
        fields = list(output_fields or ["text", "memory_type"])
        if "id" not in fields:
            fields = ["id"] + fields
        self.ensure_loaded(collection)
        try:
            kwargs = {
                "collection_name": collection,
                "data": [emb],
                "limit": top_k,
                "output_fields": fields,
                "search_params": {"metric_type": "COSINE", "params": {"nprobe": 16}},
            }
            if filter_expr:
                kwargs["filter"] = filter_expr
            results = self.client.search(**kwargs)
        except Exception as e:
            if "not loaded" in str(e).lower():
                self.ensure_loaded(collection)
                try:
                    results = self.client.search(**kwargs)
                except Exception as e2:
                    logger.error("dense_search_hits 失败: %s", e2)
                    return []
            else:
                logger.error("dense_search_hits 失败: %s", e)
                return []
        out = []
        if not results:
            return out
        for row in results[0]:
            entity = row.get("entity") or {}
            hit_id = row.get("id")
            if hit_id is None:
                hit_id = entity.get("id")
            text = entity.get("text") or row.get("text") or ""
            mem_type = entity.get("memory_type") or ""
            dist = float(row.get("distance", 0.0) or 0.0)
            out.append(
                {
                    "id": hit_id,
                    "text": text,
                    "memory_type": mem_type,
                    "score": dist,
                }
            )
        return out

    def hybrid_search(
        self, collection: str, query_text: str, dense_emb, top_k: int = 5
    ) -> List[Tuple[str, float]]:
        """
        轻量混合检索：多取一些向量候选，再按关键词命中率加成后重排。
        最终分数 = dense_score + 0.3 * keyword_hit_count
        """
        candidates = self.dense_search(collection, dense_emb, top_k=max(top_k * 3, top_k))
        if not candidates:
            return []

        tokens = _tokenize_query(query_text or "")
        ranked = []
        for text, dense_score in candidates:
            lower = (text or "").lower()
            hit = sum(1 for t in tokens if t in lower) if tokens else 0
            # 关键词命中加性加成，避免短 FAQ 被高分无关向量压制
            final = float(dense_score) + 0.3 * hit
            ranked.append((text, final))

        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


milvus_wrapper = MilvusWrapper()
