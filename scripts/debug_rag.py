import asyncio
from backend.app.rag.retriever import search_knowledge


async def test():
    print("开始调试 RAG 检索...")
    result = await search_knowledge("怎么退货", collection="faq", top_k=3, threshold=0.5)
    print(f"检索结果：{result}")


if __name__ == "__main__":
    asyncio.run(test())
