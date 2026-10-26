"""ReAct控制流、身份注入、预算，以及独立BM25/RRF的行为测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from backend.app.agent import graph
from backend.app.rag.catalog import Catalog
from backend.app.rag.ranking import bm25, reciprocal_rank_fusion
from backend.app.tools import business as tools


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args, identifier):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": identifier, "type": "tool_call"}]
    )


def initial():
    return {
        "messages": [{"role": "user", "content": "查订单1，再查京东退货规则"}],
        "user_id": "owner",
        "session_id": "test",
        "intents": [],
        "memory_hits": [],
        "tool_results": [],
    }


class ReactTests(unittest.IsolatedAsyncioTestCase):
    async def test_observe_then_choose_next_tool_and_keep_identity_private(self):
        model = ToolModel(
            responses=[
                call("lookup_order", {"order_id": 1}, "one"),
                call("search_faq", {"query": "七天无理由退货", "platform": "jd"}, "two"),
                AIMessage(content="证据已足够"),
                AIMessage(content="订单已发货；退货资格请按京东规则核对。"),
            ]
        )
        with (
            patch.object(graph, "get_chat_model", return_value=model),
            patch.object(
                tools, "query_order", AsyncMock(return_value="订单号=1 状态=已发货")
            ) as order,
            patch.object(tools, "search_knowledge", AsyncMock(return_value="有适用限制的京东规则")),
        ):
            result = await graph.build_graph().ainvoke(initial())
        order.assert_awaited_once_with("owner", order_id=1)
        self.assertEqual(result["tool_calls_count"], 2)
        self.assertEqual([r["tool"] for r in result["trace"]], ["lookup_order", "search_faq"])
        self.assertEqual(len(result["messages"]), 2)
        self.assertNotIn("证据已足够", str(result["messages"]))
        schema = tools.lookup_order.tool_call_schema.model_json_schema()["properties"]
        self.assertNotIn("state", schema)
        self.assertNotIn("user_id", schema)

    async def test_tool_round_budget_terminates_a_repeating_model(self):
        model = ToolModel(
            responses=[
                call("lookup_order", {"order_id": 1}, "one"),
                call("lookup_order", {"order_id": 1}, "two"),
                AIMessage(content="已到预算上限，仅能确认已查询内容。"),
            ]
        )
        with (
            patch.object(graph, "get_chat_model", return_value=model),
            patch.object(graph, "MAX_TOOL_ROUNDS", 2),
            patch.object(tools, "query_order", AsyncMock(return_value="订单已发货")),
        ):
            result = await graph.build_graph().ainvoke(initial())
        self.assertEqual(result["tool_calls_count"], 2)
        self.assertEqual(result["stop_reason"], "tool_round_budget")

    async def test_call_budget_supplies_observations_without_executing(self):
        model = ToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "lookup_order", "args": {"order_id": 1}, "id": "a"},
                        {"name": "lookup_order", "args": {"order_id": 2}, "id": "b"},
                    ],
                ),
                AIMessage(content="预算不足，本轮未执行查询。"),
            ]
        )
        with (
            patch.object(graph, "get_chat_model", return_value=model),
            patch.object(graph, "MAX_TOOL_CALLS", 1),
            patch.object(tools, "query_order", AsyncMock()) as order,
        ):
            result = await graph.build_graph().ainvoke(initial())
        order.assert_not_called()
        self.assertEqual(result["tool_calls_count"], 0)


class ToolSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_cannot_override_injected_user(self):
        model = ToolModel(
            responses=[
                call("lookup_order", {"order_id": 1, "state": {"user_id": "victim"}}, "malicious"),
                AIMessage(content="已取得观察"),
                AIMessage(content="仅回答当前用户订单"),
            ]
        )
        with (
            patch.object(graph, "get_chat_model", return_value=model),
            patch.object(tools, "query_order", AsyncMock(return_value="当前用户订单")) as order,
        ):
            await graph.build_graph().ainvoke(initial())
        order.assert_awaited_once_with("owner", order_id=1)

    async def test_timeout_stops_tool_loop(self):
        import asyncio

        async def slow(*args, **kwargs):
            await asyncio.sleep(0.1)
            return "too late"

        model = ToolModel(
            responses=[
                call("lookup_order", {"order_id": 1}, "slow"),
                AIMessage(content="工具超时，不能确认状态"),
            ]
        )
        with (
            patch.object(graph, "get_chat_model", return_value=model),
            patch.object(graph, "TOOL_TIMEOUT", 0.01),
            patch.object(tools, "query_order", slow),
        ):
            result = await graph.build_graph().ainvoke(initial())
        self.assertEqual(result["stop_reason"], "tool_timeout")
        self.assertEqual(result["trace"][0]["status"], "timeout")


class RankingTests(unittest.TestCase):
    def test_sparse_candidates_are_independent_from_dense(self):
        rows = [
            {"vector_id": "sku", "text": "华为FreeBuds 6i 充电盒不适用耳机IP54"},
            {"vector_id": "other", "text": "京东退货规则"},
        ]
        sparse = bm25("FreeBuds 6i 充电盒", rows)
        fused = reciprocal_rank_fusion([("other", 0.9)], sparse)
        self.assertIn("sku", [identifier for identifier, _ in fused])

    def test_rrf_uses_rank_not_incompatible_raw_score(self):
        result = reciprocal_rank_fusion([("a", 0.51), ("b", 0.5)], [("b", 900), ("a", 1)])
        self.assertAlmostEqual(dict(result)["a"], dict(result)["b"])

    def test_catalog_transactions_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog = Catalog(Path(temp) / "catalog.sqlite3")
            catalog.replace_snapshot(
                "faq",
                [{"id": 1, "text": "【天猫知识｜TM-F-0001】退货\n来源：https://www.tmall.com/"}],
                3,
            )
            self.assertEqual(catalog.rows("faq")[0]["metadata"]["platform"], "tmall")
            self.assertTrue(catalog.fresh("faq", 3))
            self.assertFalse(catalog.fresh("faq", 4))
            catalog.save_job("doc", "faq", "guide.txt", "completed", 2)
            self.assertEqual(catalog.job("doc")["chunks"], 2)


class MemoryPolicyTests(unittest.TestCase):
    def test_noisy_memory_is_filtered_without_crashing(self):
        from backend.app.memory.policy import _filter_items, _parse_extract_output

        self.assertEqual(_filter_items([{"type": "fact", "text": "订单号1已发货"}]), [])
        self.assertEqual(_parse_extract_output("invalid JSON [broken]"), [])
        self.assertEqual(
            _filter_items([{"type": "preference", "text": "以后快递不要打电话"}]),
            [{"type": "preference", "text": "以后快递不要打电话"}],
        )
