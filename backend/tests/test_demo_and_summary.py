import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_core.messages import ToolMessage

from backend.app.agent.graph import observation_summary
from backend.app.api.dependencies import verify_token
from backend.app.infrastructure.store import store
from backend.app.main import app
from backend.app.security.auth import Principal
from backend.app.tools.orders import create_demo_order, query_order


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_is_idempotent_isolated_and_labelled(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(store, "path", Path(tmp) / "db.sqlite3"),
        ):
            first = create_demo_order("alice")
            self.assertEqual(first, create_demo_order("alice"))
            self.assertLess(first["order_id"], 0)
            self.assertTrue(first["simulated"])
            own = await query_order("alice", first["order_id"])
            self.assertIn("模拟测试数据", own)
            self.assertIn("299.00", own)
            other = await query_order("bob", first["order_id"])
            self.assertNotIn("299.00", other)
            self.assertIn("未找到", other)

    async def test_demo_endpoint_requires_login_and_uses_authenticated_owner(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(store, "path", Path(tmp) / "db.sqlite3"),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                self.assertEqual((await client.post("/orders/demo")).status_code, 401)
                app.dependency_overrides[verify_token] = lambda: Principal("alice", "alice", "user")
                try:
                    response = await client.post("/orders/demo", json={"user_id": "bob"})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(
                        "模拟测试数据", await query_order("alice", response.json()["order_id"])
                    )
                    self.assertIn("未找到", await query_order("bob", response.json()["order_id"]))
                finally:
                    app.dependency_overrides.pop(verify_token, None)

    def test_summary_only_uses_tool_evidence(self):
        message = ToolMessage(
            content=json.dumps(
                {
                    "results": [{"title": "Review", "url": "https://example.org/review"}],
                    "reasoning_content": "SECRET",
                }
            ),
            name="web_search",
            tool_call_id="one",
        )
        result = observation_summary(message)
        self.assertIn("1", result["summary"])
        self.assertEqual(result["sources"][0]["url"], "https://example.org/review")
        self.assertNotIn("SECRET", json.dumps(result))
