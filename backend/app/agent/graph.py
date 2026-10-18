"""Agent 编排：节点实现与状态、提示词独立维护。"""

from functools import lru_cache
from langgraph.graph import END, StateGraph
from backend.app.agent.state import AgentState
from backend.app.agent.nodes.memory import recall_memory
from backend.app.agent.nodes.intent import classify_intents
from backend.app.agent.nodes.tools import execute_tools
from backend.app.agent.nodes.response import generate


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(AgentState)
    for name, node in [
        ("recall_memory", recall_memory),
        ("classify", classify_intents),
        ("tools", execute_tools),
        ("generate", generate),
    ]:
        graph.add_node(name, node)
    graph.set_entry_point("recall_memory")
    for source, target in [
        ("recall_memory", "classify"),
        ("classify", "tools"),
        ("tools", "generate"),
        ("generate", END),
    ]:
        graph.add_edge(source, target)
    return graph.compile()
