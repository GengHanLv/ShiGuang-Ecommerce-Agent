from typing import Annotated, TypedDict
import operator


class AgentState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    intents: list[str]
    tool_results: list[str]
    memory_hits: list[str]
    user_id: str
    session_id: str
    order_id: int | None
