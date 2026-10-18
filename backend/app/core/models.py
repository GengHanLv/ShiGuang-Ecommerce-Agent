"""模型客户端延迟创建，导入 API 不会触发模型加载或网络请求。"""

from functools import lru_cache
from backend.app.core.config import CHAT_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL


@lru_cache(maxsize=1)
def get_chat_model():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=CHAT_MODEL,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        temperature=0,
        timeout=45,
        max_retries=1,
    )


@lru_cache(maxsize=1)
def get_openai_client():
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=30, max_retries=1)
