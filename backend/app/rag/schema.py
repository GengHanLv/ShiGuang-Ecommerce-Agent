"""兼容 Milvus 2.5：新集合携带显式标量字段，旧集合完整保留供回滚。"""

import hashlib
import json
import threading

from pymilvus import DataType

from backend.app.core.config import DATA_DIR, EMBEDDING_DIM
from backend.app.infrastructure.milvus import milvus_wrapper
from backend.app.rag.metadata import SCALAR_FIELDS, scalar_values

CONFIG_PATH = DATA_DIR / "rag/collections.json"
_lock = threading.RLock()


def physical_collection(logical):
    if logical not in {"faq", "product_knowledge"}:
        raise ValueError("未知知识集合")
    if CONFIG_PATH.exists():
        values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        value = values.get(logical, logical)
        if value not in {logical, logical + "_v2"}:
            raise ValueError("集合映射不合法")
        return value
    return logical


def structured(logical):
    return physical_collection(logical).endswith("_v2")


def create_structured(name):
    client = milvus_wrapper.client
    if client.has_collection(name):
        return
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
    schema.add_field("text", DataType.VARCHAR, max_length=65535)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
    for key in SCALAR_FIELDS:
        if key in {"model_keys", "capacities"}:
            schema.add_field(
                key, DataType.ARRAY, element_type=DataType.VARCHAR, max_capacity=64, max_length=256
            )
        elif key == "model_year":
            schema.add_field(key, DataType.INT64)
        else:
            schema.add_field(key, DataType.VARCHAR, max_length=4096)
    indexes = client.prepare_index_params()
    indexes.add_index(field_name="embedding", index_type="FLAT", metric_type="COSINE")
    client.create_collection(name, schema=schema, index_params=indexes)
    client.load_collection(name)


def chunk_id(text):
    return "chunk:" + hashlib.sha256(text.encode()).hexdigest()


def migrate_collections():
    """幂等 upsert 原始向量；逐行校验正文、向量和字段后才原子切换映射。"""
    client = milvus_wrapper.client
    report = {}
    with _lock:
        mapping = {}
        for logical in ("product_knowledge", "faq"):
            target = logical + "_v2"
            create_structured(target)
            count = 0
            if client.has_collection(logical):
                client.load_collection(logical)
                iterator = client.query_iterator(
                    collection_name=logical,
                    filter="",
                    output_fields=["id", "text", "embedding"],
                    batch_size=64,
                )
                try:
                    while rows := iterator.next():
                        converted = [
                            {
                                "id": "legacy:" + str(r["id"]),
                                "text": r["text"],
                                "embedding": r["embedding"],
                                **scalar_values(r["text"]),
                            }
                            for r in rows
                        ]
                        client.upsert(collection_name=target, data=converted)
                        actual = {
                            r["id"]: r
                            for r in client.get(
                                collection_name=target,
                                ids=[r["id"] for r in converted],
                                output_fields=["id", "text", "embedding", *SCALAR_FIELDS],
                                consistency_level="Strong",
                            )
                        }
                        for expected in converted:
                            stored = actual.get(expected["id"])
                            if (
                                not stored
                                or stored["text"] != expected["text"]
                                or len(stored["embedding"]) != len(expected["embedding"])
                            ):
                                raise RuntimeError("迁移校验失败，继续使用原集合")
                            if any(
                                abs(a - b) > 1e-6
                                for a, b in zip(stored["embedding"], expected["embedding"])
                            ):
                                raise RuntimeError("迁移向量不一致")
                            if any(stored[k] != expected[k] for k in SCALAR_FIELDS):
                                raise RuntimeError("迁移标量字段不一致")
                        count += len(rows)
                finally:
                    iterator.close()
            client.flush(collection_name=target)
            mapping[logical] = target
            report[logical] = {
                "physical": target,
                "legacy_rows_verified": count,
                "original_preserved": True,
            }
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = CONFIG_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        temp.replace(CONFIG_PATH)
    return report
