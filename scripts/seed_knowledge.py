"""增量写入公开虚构样例，无重置或删除操作。"""

import asyncio
from pathlib import Path
from backend.app.infrastructure.embeddings import embed_texts
from backend.app.infrastructure.milvus import milvus_wrapper
from backend.app.rag.retriever import invalidate_knowledge_cache
from backend.app.infrastructure.redis import close_redis

ROOT = Path(__file__).resolve().parents[1]


def seed():
    client = milvus_wrapper.client
    try:
        for collection in ("product_knowledge", "faq"):
            milvus_wrapper.create_collection(collection)
            texts = [
                line.strip()
                for line in (ROOT / "examples" / f"{collection}.txt")
                .read_text(encoding="utf-8")
                .splitlines()[1:]
                if line.strip()
            ]
            iterator = client.query_iterator(
                collection_name=collection, filter="", output_fields=["text"], batch_size=256
            )
            existing = set()
            try:
                while batch := iterator.next():
                    existing.update(row["text"] for row in batch)
            finally:
                iterator.close()
            pending = [text for text in texts if text not in existing]
            if pending:
                vectors = embed_texts(pending)
                client.insert(
                    collection_name=collection,
                    data=[
                        {"text": text, "embedding": vector}
                        for text, vector in zip(pending, vectors)
                    ],
                )
                client.flush(collection_name=collection)
            print(collection, "inserted=", len(pending), "skipped=", len(texts) - len(pending))

        async def invalidate():
            for collection in ("product_knowledge", "faq"):
                await invalidate_knowledge_cache(collection)
            await close_redis()

        asyncio.run(invalidate())
    finally:
        milvus_wrapper.close()


if __name__ == "__main__":
    seed()
