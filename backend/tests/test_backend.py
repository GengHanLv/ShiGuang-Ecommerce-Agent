"""Protect behavior affected by the refactor without network or model calls."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from backend.app.api.dependencies import require_admin, verify_token
from backend.app.api.routes import chat as chat_routes
from backend.app.core.config import API_KEY
from backend.app.infrastructure.store import store
from backend.app.main import app
from backend.app.memory.session import SessionManager, _memory_store
from backend.app.rag.ingestion import split_text
from backend.app.security.auth import Principal


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_patch = patch.object(store, "path", Path(self.temp.name) / "app.sqlite3")
        self.store_patch.start()
        self.env_patch = patch.dict("os.environ", {"RAG_RERANKER": "rules"})
        self.env_patch.start()
        app.dependency_overrides[verify_token] = lambda: Principal("u", "tester", "admin")
        app.dependency_overrides[require_admin] = lambda: Principal("u", "tester", "admin")
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        self.headers = {"X-API-Key": API_KEY}

    async def asyncTearDown(self):
        await self.http.aclose()
        app.dependency_overrides.clear()
        self.env_patch.stop()
        self.store_patch.stop()
        self.temp.cleanup()

    async def test_health_auth_and_validation(self):
        self.assertEqual((await self.http.get("/health")).status_code, 200)
        app.dependency_overrides.pop(verify_token)
        self.assertEqual((await self.http.post("/chat", json={"message": "hi"})).status_code, 401)
        app.dependency_overrides[verify_token] = lambda: Principal("u", "tester", "admin")
        response = await self.http.post(
            "/chat", headers=self.headers, json={"user_id": "u", "message": "   "}
        )
        self.assertEqual(response.status_code, 422)

    async def test_generated_session_id_is_persisted_consistently(self):
        graph = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value={
                    "messages": [{"role": "assistant", "content": "reply"}],
                    "intents": ["chitchat"],
                    "product_images": [
                        {
                            "model": "示例型号",
                            "url": "https://www.apple.com.cn/image.png",
                            "alt": "官网产品图",
                            "source_url": "https://www.apple.com.cn/",
                        }
                    ],
                }
            )
        )
        with (
            patch.object(chat_routes, "build_graph", return_value=graph),
            patch.object(SessionManager, "get_history", AsyncMock(return_value=[])),
            patch.object(SessionManager, "save_history", AsyncMock()) as save,
            patch.object(chat_routes, "extract_and_save_memories", AsyncMock(return_value=0)),
        ):
            response = await self.http.post(
                "/chat", headers=self.headers, json={"user_id": "u", "message": "hello"}
            )
            result = response.json()
            state = graph.ainvoke.call_args.args[0]
            self.assertEqual(state["session_id"], result["session_id"])
            self.assertEqual(save.call_args.args[0], result["session_id"])
            self.assertEqual(save.call_args.args[2], "u")
            self.assertEqual(result["product_images"][0]["model"], "示例型号")

    async def test_sse_hides_classifier_tokens_and_persists_final_reply(self):
        async def events(*args, **kwargs):
            yield {
                "event": "on_chat_model_stream",
                "tags": [],
                "data": {"chunk": SimpleNamespace(content="knowledge")},
            }
            yield {
                "event": "on_chat_model_stream",
                "tags": ["response"],
                "data": {"chunk": SimpleNamespace(content="你好")},
            }
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {
                    "output": {
                        "messages": [{"role": "assistant", "content": "你好"}],
                        "intents": ["chitchat"],
                        "memory_hits": [],
                        "product_images": [
                            {
                                "model": "示例型号",
                                "url": "https://www.apple.com.cn/image.png",
                                "alt": "官网产品图",
                                "source_url": "https://www.apple.com.cn/",
                            }
                        ],
                    }
                },
            }

        graph = SimpleNamespace(astream_events=events)
        with (
            patch.object(chat_routes, "build_graph", return_value=graph),
            patch.object(SessionManager, "get_history", AsyncMock(return_value=[])),
            patch.object(SessionManager, "save_history", AsyncMock()),
            patch.object(chat_routes, "extract_and_save_memories", AsyncMock(return_value=0)),
        ):
            response = await self.http.post(
                "/chat/stream",
                headers=self.headers,
                json={"user_id": "u", "message": "hello", "session_id": "s"},
            )
            payloads = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            self.assertEqual([p["type"] for p in payloads], ["task", "token", "done"])
            self.assertEqual(payloads[1]["content"], "你好")
            self.assertEqual(payloads[2]["session_id"], "s")
            self.assertEqual(payloads[2]["product_images"][0]["model"], "示例型号")

    async def test_chat_failure_is_explicitly_marked(self):
        graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("unavailable")))
        with (
            patch.object(chat_routes, "build_graph", return_value=graph),
            patch.object(SessionManager, "get_history", AsyncMock(return_value=[])),
        ):
            response = await self.http.post(
                "/chat", headers=self.headers, json={"user_id": "u", "message": "hello"}
            )
            self.assertTrue(response.json()["degraded"])

    async def test_session_isolation_and_defensive_copy(self):
        _memory_store.clear()
        with patch("backend.app.memory.session.get_redis", AsyncMock(return_value=None)):
            await SessionManager.save_history(
                "same", [{"role": "user", "content": "private"}], "alice"
            )
            self.assertEqual(await SessionManager.get_history("same", "bob"), [])
            first = await SessionManager.get_history("same", "alice")
            first[0]["content"] = "modified"
            self.assertEqual(
                (await SessionManager.get_history("same", "alice"))[0]["content"], "private"
            )

    async def test_upload_rejects_empty_or_wrong_collection(self):
        response = await self.http.post(
            "/upload", headers=self.headers, files={"file": ("empty.txt", b"", "text/plain")}
        )
        self.assertEqual(response.status_code, 400)
        response = await self.http.post(
            "/upload",
            headers=self.headers,
            data={"collection": "user_memory"},
            files={"file": ("data.txt", b"hello", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)

    async def test_upload_reports_count_invalidates_cache_and_cleans_file(self):
        import tempfile
        from pathlib import Path

        from backend.app.api.routes import knowledge

        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(knowledge, "DATA_DIR", Path(temp)),
            patch.object(knowledge, "process_document", AsyncMock(return_value=2)),
            patch.object(knowledge, "invalidate_knowledge_cache", AsyncMock()) as invalidate,
        ):
            response = await self.http.post(
                "/upload",
                headers=self.headers,
                data={"collection": "faq"},
                files={"file": ("guide.txt", b"sample", "text/plain")},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["chunks"], 2)
            invalidate.assert_awaited_once_with("faq")
            self.assertEqual(list(Path(temp).iterdir()), [])

    async def test_new_knowledge_invalidates_cached_answers(self):
        from unittest.mock import Mock

        from backend.app.rag import retriever

        retriever._memory_cache.clear()
        retriever._cache_versions.clear()
        row = {"vector_id": "7", "text": "old answer", "metadata": {"platform": "generic"}}
        rows = Mock(return_value=[row])
        dense = Mock(return_value=[{"id": 7, "text": "old answer", "score": 0.9}])
        with (
            patch.object(retriever, "get_redis", AsyncMock(return_value=None)),
            patch.object(retriever, "aembed_text", AsyncMock(return_value=[1.0])),
            patch.object(retriever, "sync_catalog", Mock()),
            patch.object(retriever.catalog, "rows", rows),
            patch.object(retriever.milvus_wrapper, "dense_search_hits", dense),
        ):
            first = json.loads(await retriever.search_knowledge("sample", "faq"))
            self.assertEqual(first["evidence"][0]["text"], "old answer")
            row = {"vector_id": "7", "text": "new answer", "metadata": {"platform": "generic"}}
            rows.return_value = [row]
            dense.return_value = [{"id": 7, "text": "new answer", "score": 0.9}]
            cached = json.loads(await retriever.search_knowledge("sample", "faq"))
            self.assertEqual(cached["evidence"][0]["text"], "old answer")
            await retriever.invalidate_knowledge_cache("faq")
            updated = json.loads(await retriever.search_knowledge("sample", "faq"))
            self.assertEqual(updated["evidence"][0]["text"], "new answer")

    def test_long_unpunctuated_document_is_bounded_without_gaps(self):
        source = "".join(chr(0x4E00 + i) for i in range(2300))
        chunks = split_text(source, 500, 50)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        reconstructed = chunks[0] + "".join(c[50:] for c in chunks[1:])
        self.assertEqual(reconstructed, source)
        with self.assertRaises(ValueError):
            split_text("text", 50, 50)


if __name__ == "__main__":
    unittest.main()
