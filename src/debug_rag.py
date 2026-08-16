import asyncio
from rag_tool import search_knowledge

async def test():
    print("开始调试 RAG 检索...")
    result = await search_knowledge("怎么退货", collection="faq", top_k=3, threshold=0.5)
    print(f"检索结果：{result}")

asyncio.run(test())