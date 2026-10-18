import logging
from typing import List
from backend.app.agent.state import AgentState

logger = logging.getLogger(__name__)

from backend.app.memory.long_term import search_user_memory
from backend.app.memory.signals import should_inject_memory
from backend.app.agent.nodes.intent import _rule_intents


async def recall_memory(state: AgentState):
    msg = state["messages"][-1]["content"]
    if not should_inject_memory(msg, True) or _rule_intents(msg) == ["transfer_human"]:
        return {"memory_hits": []}
    user_id = state.get("user_id") or ""
    hits = await search_user_memory(user_id, msg)
    logger.info("recall_memory | user=%s hits=%d", user_id, len(hits))
    return {"memory_hits": hits}
