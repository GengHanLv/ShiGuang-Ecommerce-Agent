"""持久化恢复、身份隔离、型号约束、来源日期、精排和联网图片的行为验证。"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.app.agent import graph, journal
from backend.app.infrastructure.store import store
from backend.app.main import app
from backend.app.memory.preferences import delete_preference, list_preferences, set_preference
from backend.app.rag import media, reranker
from backend.app.rag.entities import matches, parse_scope, scalar_filter
from backend.app.rag.ingestion import split_text
from backend.app.rag.metadata import metadata
from backend.app.tools import business as tools
from backend.app.tools import web as research
from backend.app.tools.http import public_address


class IsolatedStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(store, "path", Path(self.temp.name) / "app.sqlite3")
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp.cleanup()


class IdentityTests(IsolatedStore):
    async def test_login_roles_forged_identity_and_logout(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            registered = await http.post(
                "/auth/register", json={"username": "student01", "password": "good-password-123"}
            )
            self.assertEqual(registered.status_code, 200)
            owner = registered.json()["id"]
            self.assertNotEqual(owner, "user123")
            self.assertEqual(
                (
                    await http.post(
                        "/auth/login", json={"username": "student01", "password": "wrong-password"}
                    )
                ).status_code,
                401,
            )
            response = await http.post(
                "/auth/login", json={"username": "student01", "password": "good-password-123"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("HttpOnly", response.headers["set-cookie"])
            self.assertEqual((await http.get("/auth/me")).json()["id"], owner)
            self.assertEqual(
                (
                    await http.post("/chat", json={"message": "查订单", "user_id": "user123"})
                ).status_code,
                403,
            )
            self.assertEqual((await http.post("/tools/reload")).status_code, 403)
            self.assertEqual(
                (await http.post("/upload", files={"file": ("a.txt", b"a")})).status_code, 403
            )
            other = journal.create_run("another-user", "same", "once", "private")
            self.assertEqual((await http.get("/tasks/" + other["id"])).status_code, 404)
            self.assertEqual(
                (await http.post("/tasks/" + other["id"] + "/resume")).status_code, 404
            )
            self.assertEqual((await http.get("/sessions/same/history")).json()["messages"], [])
            self.assertEqual(
                (
                    await http.post(
                        "/preferences",
                        headers={"Origin": "https://evil.example"},
                        json={"text": "以后晚上收货"},
                    )
                ).status_code,
                403,
            )
            await http.post("/auth/logout")
            self.assertEqual((await http.get("/auth/me")).status_code, 401)

    async def test_preferences_version_and_user_scope(self):
        first = set_preference("a", "以后晚上收货")
        second = set_preference("a", "以后早上收货", first["version"])
        self.assertGreater(second["version"], first["version"])
        self.assertEqual(len(list_preferences("a")), 1)
        self.assertEqual(list_preferences("b"), [])
        with self.assertRaises(Exception):
            set_preference("a", "以后晚上收货", first["version"])
        self.assertEqual(delete_preference("b", first["topic"]), 0)


class RecoveryTests(IsolatedStore):
    async def test_first_request_without_session_is_idempotent_and_owned(self):
        from backend.app.api.routes.chat import request_run
        from backend.app.api.schemas import ChatRequest
        from backend.app.security.auth import Principal

        user = Principal("a", "alice", "user")
        first = request_run(ChatRequest(message="hello", request_id="stable"), user)
        replay = request_run(ChatRequest(message="hello", request_id="stable"), user)
        other = request_run(
            ChatRequest(message="hello", request_id="stable"), Principal("b", "bob", "user")
        )
        self.assertEqual(first["id"], replay["id"])
        self.assertNotEqual(first["id"], other["id"])
        with self.assertRaises(Exception):
            request_run(ChatRequest(message="changed", request_id="stable"), user)
        journal.start_tool(first["id"], "unsafe", "external", {}, False)
        self.assertFalse(journal.retry_allowed(first["id"]))
        journal.finish_tool(first["id"], "unsafe", {"ok": True}, True)
        self.assertTrue(journal.retry_allowed(first["id"]))

    async def test_checkpoint_reopens_after_failure_without_repeating_completed_tool(self):
        class ToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = ToolModel(
            responses=[
                AIMessage(
                    content="", tool_calls=[{"name": "lookup_order", "args": {}, "id": "read-once"}]
                ),
                AIMessage(content="资料已取得"),
                AIMessage(content="订单已发货。"),
            ]
        )
        real_finalize = graph.finalize
        attempts = 0

        async def flaky(state):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("simulate process failure before generation")
            return await real_finalize(state)

        row = journal.create_run("owner", "session", "request", "查询订单")
        state = {
            "messages": [{"role": "user", "content": "查询订单"}],
            "user_id": "owner",
            "session_id": "session",
            "run_id": row["id"],
            "tool_results": [],
        }
        config = {"configurable": {"thread_id": row["id"]}}
        path = str(Path(self.temp.name) / "checkpoints.sqlite3")
        with (
            patch.object(graph, "get_chat_model", return_value=model),
            patch.object(graph, "finalize", flaky),
            patch.object(tools, "query_order", AsyncMock(return_value="订单已发货")) as order,
            patch.object(graph.registry, "tools", []),
        ):
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                agent = graph.build_graph(saver)
                with self.assertRaises(RuntimeError):
                    await agent.ainvoke(state, config=config, durability="sync")
                self.assertIn("generate", (await agent.aget_state(config)).next)
            # 重新打开持久化文件并构建新图，模拟服务重启。
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                result = await graph.build_graph(saver).ainvoke(
                    None, config=config, durability="sync"
                )
            self.assertEqual(result["messages"][-1]["content"], "订单已发货。")
            order.assert_awaited_once_with("owner", order_id=None)
            self.assertEqual(journal.public_tools(row["id"])[0]["attempts"], 1)

    async def test_tool_receipt_replay_and_nonretryable_uncertainty(self):
        row = journal.create_run("a", "s", "r", "q")
        args = {"query": "public product"}
        self.assertIsNone(journal.start_tool(row["id"], "one", "read", args, True))
        receipt = {"content": "done", "name": "read", "tool_call_id": "one", "status": "success"}
        journal.finish_tool(row["id"], "one", receipt, True)
        self.assertEqual(journal.start_tool(row["id"], "one", "read", args, True), receipt)
        journal.start_tool(row["id"], "two", "write", {}, False)
        with self.assertRaises(RuntimeError):
            journal.start_tool(row["id"], "two", "write", {}, False)
        with self.assertRaises(Exception):
            journal.create_run("a", "s", "r", "different question")


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_sufficiency_requires_each_model_and_matching_condition(self):
        def evidence(title, text):
            return {**metadata(title), "text": text}

        wrong = evidence("AirPods Pro 2", "开启降噪续航6小时")
        self.assertFalse(reranker.assess_evidence("AirPods 4 开启降噪续航", [wrong])["sufficient"])
        off = evidence("AirPods 4", "支持降噪。关闭降噪续航5小时")
        self.assertFalse(reranker.assess_evidence("AirPods 4 开启降噪续航", [off])["sufficient"])
        on = evidence("AirPods 4", "开启降噪续航4小时")
        self.assertTrue(reranker.assess_evidence("AirPods 4 开启降噪续航", [on])["sufficient"])
        self.assertFalse(
            reranker.assess_evidence("AirPods 4 与 AirPods Pro 2 开启降噪续航", [on])["sufficient"]
        )

    async def test_condition_and_value_on_adjacent_lines_stay_together(self):
        text = "前言。" * 25 + "开启降噪\n最长可达5小时。" + "说明。" * 25
        self.assertTrue(any("开启降噪：最长可达5小时" in c for c in split_text(text, 100, 10)))

    async def test_models_variants_capacity_year_and_scalar_filter(self):
        base = metadata(
            "【天猫知识｜TM-P-0001】iPhone 16 标准版 256GB 2024款\n来源：https://www.apple.com.cn/iphone-16/specs/"
        )
        for question in ["iPhone 16 Pro", "iPhone 16 512GB", "iPhone 16 2025款"]:
            self.assertFalse(matches(base, parse_scope(question)), question)
        self.assertTrue(matches(base, parse_scope("iPhone 16 标准版256GB 2024款")))
        self.assertIn(
            "array_contains(model_keys", scalar_filter(parse_scope("iPhone 16 Pro"), "tmall")
        )
        self.assertFalse(
            matches(metadata("罗技 MX Master 3S 商用版"), parse_scope("MX Master 3S 标准版"))
        )

    async def test_source_dates_do_not_alias_review_time(self):
        meta = metadata("产品\n发布日期：2024-01-02\n生效日期：2024-02-03\n核验日期：2026-10-26")
        self.assertEqual(
            (meta["published_at"], meta["effective_at"], meta["reviewed_at"]),
            ("2024-01-02", "2024-02-03", "2026-10-26"),
        )
        self.assertEqual(metadata("产品\n核验日期：2026-10-26")["published_at"], "")

    async def test_reranker_rejects_unrelated_candidates_and_unknown_ids(self):
        candidates = [
            {
                "id": "a",
                "title": "iPhone 16 USB接口",
                "text": "USB 2 480Mb/s",
                "model_keys": ["iphone16"],
                "rrf_score": 1,
            },
            {
                "id": "b",
                "title": "iPhone 16 色彩",
                "text": "颜色",
                "model_keys": ["iphone16"],
                "rrf_score": 2,
            },
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            choices=[
                                SimpleNamespace(
                                    message=SimpleNamespace(
                                        content='[{"id":"a","score":3},{"id":"b","score":0}]'
                                    )
                                )
                            ]
                        )
                    )
                )
            )
        )
        with (
            patch.object(reranker, "get_openai_client", return_value=api),
            patch.dict("os.environ", {"RAG_RERANKER": "llm"}),
        ):
            result = await reranker.rerank("iPhone 16 USB传输", candidates)
        self.assertEqual([r["id"] for r in result], ["a"])
        self.assertFalse(
            reranker.assess_evidence("iPhone 16 现在多少钱", [candidates[0]])["sufficient"]
        )

    async def test_long_tables_keep_header_and_each_condition_row(self):
        header = "| 状态 | 续航 |\n|---|---|\n"
        rows = [f"| 开启降噪 {i} | 5小时 |" for i in range(80)]
        chunks = split_text(header + "\n".join(rows), 180, 20)
        self.assertTrue(all(c.startswith("| 状态 | 续航 |") and len(c) <= 180 for c in chunks))
        for row in rows:
            self.assertTrue(any(row in chunk for chunk in chunks))


class OnlineMediaTests(IsolatedStore):
    async def test_web_sku_filter_excludes_other_capacity_and_offers(self):
        html = b"""<html><title>iPhone 16 256GB</title>
        <script type="application/ld+json">[
        {"@type":"Product","name":"iPhone 16 256GB","offers":{"price":100}},
        {"@type":"Product","name":"iPhone 16 Pro 512GB","offers":{"price":200}}
        ]</script></html>"""
        with patch.object(
            research,
            "fetch_public",
            AsyncMock(
                return_value=("https://www.apple.com/product", {"content-type": "text/html"}, html)
            ),
        ):
            correct = await research.fetch_product_page(
                "https://www.apple.com/product", "iPhone 16 256GB"
            )
            wrong = await research.fetch_product_page(
                "https://www.apple.com/product", "iPhone 16 512GB"
            )
        self.assertTrue(correct["model_match"])
        self.assertEqual(correct["offers"], [{"price": 100}])
        self.assertFalse(wrong["model_match"])
        self.assertEqual(wrong["offers"], [])

    async def test_page_extracts_real_images_and_rejects_other_model(self):
        html = b'<html><head><title>iPhone 16 Pro</title><meta property="og:image" content="https://cdn.example/product.png"></head><body>Specifications</body></html>'
        with (
            patch.object(
                research,
                "fetch_public",
                AsyncMock(
                    return_value=(
                        "https://www.apple.com/product",
                        {"content-type": "text/html"},
                        html,
                    )
                ),
            ),
            patch.object(research, "public_address", AsyncMock()),
        ):
            correct = await research.fetch_product_page(
                "https://www.apple.com/product", "iPhone 16 Pro"
            )
            wrong = await research.fetch_product_page("https://www.apple.com/product", "iPhone 16")
        self.assertTrue(correct["model_match"])
        self.assertTrue(correct["images"][0]["url"].startswith("/media/"))
        self.assertFalse(wrong["model_match"])
        self.assertEqual(wrong["images"], [])
        with store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM web_assets").fetchone()[0], 1)

    async def test_gallery_requires_a_successful_matching_web_observation(self):
        asset = {
            "model": "iPhone 16",
            "url": "/media/" + "a" * 64,
            "alt": "产品图",
            "source_url": "https://www.apple.com/product",
        }
        result = {"model": "iPhone 16", "model_match": True, "images": [asset]}
        with patch.object(media.registry, "tools", [SimpleNamespace(name="fetch_product_page")]):
            selected = await media.resolve_product_images(
                [
                    HumanMessage("iPhone16"),
                    ToolMessage(
                        content=json.dumps(result), name="fetch_product_page", tool_call_id="one"
                    ),
                ],
                "iPhone 16规格",
            )
            self.assertEqual(selected, [asset])

    async def test_private_addresses_and_deceptive_official_hosts_are_rejected(self):
        for url in [
            "http://127.0.0.1/x",
            "http://169.254.169.254/",
            "http://[::1]/",
            "file:///secret",
            "https://user:pass@example.com/",
        ]:
            with self.assertRaises(ValueError):
                await public_address(url)
        with patch.dict("os.environ", {"WEB_ALLOWED_DOMAINS": "apple.com,apple.com.cn"}):
            self.assertFalse(research.trusted_host("apple.com.evil.example"))
            self.assertTrue(research.trusted_host("www.apple.com.cn"))
        self.assertEqual(
            research.source_kind("https://apple.com.evil.example/product"), "third_party_page"
        )
