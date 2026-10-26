"""电商工具的确定性计算、私有导出与恢复行为。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from pypdf import PdfReader

from backend.app.agent import journal
from backend.app.api.dependencies import verify_token
from backend.app.infrastructure.store import store
from backend.app.main import app
from backend.app.security.auth import Principal
from backend.app.tools import business, documents, registry
from backend.app.tools.commerce import (
    CartItem,
    ProductCandidate,
    compare_candidates,
    purchase_cost,
    service_window,
)


class CommerceTests(unittest.TestCase):
    def test_decimal_total_and_budget(self):
        result = purchase_cost(
            [CartItem(name="配件", unit_price="0.10", quantity=3)],
            discount="0.10",
            shipping="2.00",
            budget="2.20",
        )
        self.assertEqual(result["total"], "2.20")
        self.assertTrue(result["within_budget"])
        for value in ("NaN", "-1", "Infinity", "0.001", "999"):
            with self.assertRaises(ValueError):
                purchase_cost([CartItem(name="配件", unit_price="1", quantity=1)], discount=value)

    def test_comparison_preserves_unknowns_and_conditions(self):
        result = compare_candidates(
            [
                ProductCandidate(model="A", specifications={"续航": "开启降噪5小时"}),
                ProductCandidate(model="B", specifications={"续航": "关闭降噪8小时"}),
            ],
            ["续航", "防水"],
        )
        self.assertEqual(result["rows"][0]["values"], ["开启降噪5小时", "关闭降噪8小时"])
        self.assertEqual(result["rows"][1]["values"], ["当前资料无法确认"] * 2)

    def test_date_arithmetic_explicit_counting(self):
        self.assertEqual(service_window("2024-02-28", 2)["end_date"], "2024-03-01")
        self.assertEqual(service_window("2024-02-28", 2, True)["end_date"], "2024-02-29")
        with self.assertRaises(ValueError):
            service_window("2024-02-30", 7)

    def test_native_identity_is_not_in_model_schema(self):
        for tool in (business.export_consultation_pdf, business.list_saved_documents):
            schema = tool.tool_call_schema.model_json_schema()
            self.assertNotIn("state", schema["properties"])
            self.assertNotIn("user_id", schema["properties"])

    def test_old_mcp_configuration_is_read_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "servers.json"
            text = json.dumps(
                {
                    "servers": {
                        "web": {
                            "args": ["-m", "backend.app.integrations.mcp_server"],
                            "allow_tools": ["current_time"],
                        }
                    }
                }
            )
            path.write_text(text)
            with patch.object(registry, "CONFIG", path):
                config = registry.read_config()
            self.assertEqual(config["servers"]["web"]["args"][-1], "backend.app.tools.server")
            self.assertEqual(config["servers"]["web"]["allow_tools"], ["current_time"])
            self.assertEqual(path.read_text(), text)


class DocumentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patches = [
            patch.object(store, "path", self.folder / "app.sqlite3"),
            patch.object(documents, "EXPORT_DIR", self.folder / "exports"),
            patch("backend.app.memory.session.get_redis", AsyncMock(return_value=None)),
            patch("backend.app.memory.session._memory_store", {}),
        ]
        for p in self.patches:
            p.start()
        app.dependency_overrides[verify_token] = lambda: Principal("owner", "alice", "user")
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.http.aclose()
        app.dependency_overrides.clear()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def test_export_download_owner_and_idempotency(self):
        row = journal.create_run("owner", "s", "r", "总结商品续航")
        journal.update_run(row["id"], "completed", "completed", {"reply": "开启降噪：5小时。"})
        first = await self.http.post("/documents/from-task/" + row["id"])
        self.assertEqual(first.status_code, 200)
        doc = first.json()["document"]
        second = await self.http.post("/documents/from-task/" + row["id"])
        self.assertEqual(doc["id"], second.json()["document"]["id"])
        self.assertEqual(len(list((self.folder / "exports").glob("*.pdf"))), 1)
        response = await self.http.get(doc["download_url"])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("attachment", response.headers["content-disposition"])
        reader = PdfReader(self.folder / "exports" / (doc["id"] + ".pdf"))
        self.assertIn("开启降噪", "".join(p.extract_text() for p in reader.pages))
        app.dependency_overrides[verify_token] = lambda: Principal("other", "bob", "user")
        self.assertEqual((await self.http.get(doc["download_url"])).status_code, 404)
        self.assertEqual(
            (await self.http.post("/documents/from-task/" + row["id"])).status_code, 404
        )
        self.assertEqual((await self.http.get("/documents")).json()["documents"], [])

    async def test_agent_pdf_tool_survives_task_replay_and_returns_download_card(self):
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage
        from langgraph.checkpoint.memory import InMemorySaver

        from backend.app.agent import graph
        from backend.app.api.routes import chat

        class ToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = ToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "export_consultation_pdf",
                            "id": "pdf-call",
                            "args": {
                                "title": "选购摘要",
                                "sections": [
                                    {"heading": "待核实", "content": "当前资料无法确认续航。"}
                                ],
                            },
                        }
                    ],
                ),
                AIMessage(content="整理完成"),
                AIMessage(content="已生成选购摘要，可下载PDF。"),
            ]
        )
        row = journal.create_run("owner", "session", "once", "将选购摘要导出PDF")
        with (
            patch.object(graph, "get_chat_model", return_value=model),
            patch.object(registry.registry, "tools", []),
        ):
            agent = graph.build_graph(InMemorySaver())
            events = [event async for event in chat.run_events(row, agent)]
            replay = [event async for event in chat.run_events(row, agent)]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(len(events[-1]["documents"]), 1)
        self.assertEqual(events[-1]["documents"], replay[-1]["documents"])
        self.assertEqual(journal.public_tools(row["id"])[0]["attempts"], 1)

    async def test_tool_requires_export_intent_and_escapes_markup(self):
        state = {"user_id": "owner", "run_id": "r", "messages": [{"content": "介绍商品"}]}
        section = documents.ReportSection(
            heading="注意", content='<img src="file:///secret"/> 未核实'
        )
        with self.assertRaises(ValueError):
            await business.export_consultation_pdf.ainvoke(
                {"title": "报告", "sections": [section], "state": state}
            )
        state["messages"][-1]["content"] = "请导出PDF"
        result = json.loads(
            await business.export_consultation_pdf.ainvoke(
                {"title": "报告", "sections": [section], "state": state}
            )
        )
        doc = result["document"]
        reader = PdfReader(self.folder / "exports" / (doc["id"] + ".pdf"))
        self.assertIn("file:///secret", reader.pages[0].extract_text())
        self.assertEqual(len(reader.pages[0].images), 0)

    async def test_incomplete_run_cannot_export_and_paths_are_not_accepted(self):
        row = journal.create_run("owner", "s", "r", "q")
        self.assertEqual(
            (await self.http.post("/documents/from-task/" + row["id"])).status_code, 409
        )
        with self.assertRaises(Exception):
            documents.owned_document("../secret", "owner")
