"""对话历史与 ReAct 内部消息分开，内部规划不进入浏览器历史。"""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # 对外仅保留 user/assistant；旧会话结构可以继续使用。
    messages: Annotated[list[dict], operator.add]
    # 对内保留 AIMessage.tool_calls 和 ToolMessage，供下一轮模型观察。
    react_messages: Annotated[list[BaseMessage], add_messages]
    intents: list[str]
    tool_results: Annotated[list[str], operator.add]
    memory_hits: list[str]
    user_id: str
    session_id: str
    run_id: str
    request_id: str
    order_id: int | None
    steps: int
    tool_calls_count: int
    stop_reason: str
    # 联网 MCP 从实际商品网页发现配图，浏览器通过已登记资产代理读取。
    product_images: list[dict]
    # 只记录工具名、耗时、状态，不记录模型内部思考。
    trace: Annotated[list[dict], operator.add]
