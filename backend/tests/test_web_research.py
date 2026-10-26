import unittest
from unittest.mock import AsyncMock, patch

from backend.app.rag.entities import model_keys
from backend.app.tools import web


class WebResearchTests(unittest.IsolatedAsyncioTestCase):
    def test_public_sources_are_allowed_without_claiming_official(self):
        with patch.dict("os.environ", {"WEB_ALLOWED_DOMAINS": ""}):
            self.assertTrue(web.trusted_host("community.example.org"))
            self.assertEqual(
                web.source_kind("https://community.example.org/review"), "third_party_page"
            )
        with patch.dict("os.environ", {"WEB_ALLOWED_DOMAINS": "edifier.com"}):
            self.assertFalse(web.trusted_host("community.example.org"))
            self.assertTrue(web.trusted_host("www.edifier.com"))

    def test_model_alias_and_version(self):
        self.assertEqual(model_keys("联想拯救者Y9000P"), model_keys("Y9000P"))
        self.assertFalse(set(model_keys("Y9000P")).intersection(model_keys("拯救者Y9000P至尊版")))
        self.assertFalse(set(model_keys("Y9000P")).intersection(model_keys("Y7000P")))

    def test_homepage_and_wrong_model_are_not_evidence(self):
        rows = [
            {"href": "https://www.lenovo.com.cn/", "title": "Y9000P 联想首页"},
            {"href": "https://item.jd.com/123.html", "title": "拯救者Y7000P"},
        ]
        self.assertEqual(web.relevant_rows(rows, "拯救者 Y9000P"), [])

    async def test_homepage_triggers_targeted_fallback_and_diversity(self):
        async def search(query, provider, count):
            if provider == "bing_rss":
                return [{"href": "https://www.lenovo.com.cn/", "title": "联想官网"}]
            if "site:jd.com" in query:
                return [{"href": "https://item.jd.com/123.html", "title": "Y9000P 商品"}]
            if "评测" in query:
                return [
                    {"href": "https://www.ithome.com/0/123/456.htm", "title": "拯救者Y9000P 评测"}
                ]
            return [{"href": "https://www.lenovo.com.cn/product/123.html", "title": "Y9000P 参数"}]

        with (
            patch.dict(
                "os.environ",
                {"WEB_SEARCH_PROVIDER": "auto", "TAVILY_API_KEY": "", "WEB_ALLOWED_DOMAINS": ""},
            ),
            patch.object(web, "search_provider", side_effect=search) as called,
            patch.object(web, "public_address", new=AsyncMock()),
        ):
            result = await web.web_search("拯救者 Y9000P 价格 配置 测评 京东")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(called.call_count, 4)
        self.assertEqual(
            {r["source_type"] for r in result["results"]},
            {"brand_page", "merchant_page", "third_party_page"},
        )
        self.assertTrue(all(r["evidence_type"] == "search_snippet" for r in result["results"]))

    async def test_outage_is_not_claimed_as_absence_of_product(self):
        with patch.object(web, "search_provider", side_effect=OSError("offline")):
            result = await web.web_search("Y9000P")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["results"], [])

    async def test_third_party_page_source_and_lazy_image(self):
        html = b'<html><title>Y9000P review</title><meta property="article:published_time" content="2025-08-01"><img alt="Y9000P" data-src="https://img.example.com/photo.jpg"><p>test conditions</p></html>'
        with (
            patch.object(
                web,
                "fetch_public",
                new=AsyncMock(
                    return_value=(
                        "https://www.ithome.com/0/123/456.htm",
                        {"content-type": "text/html"},
                        html,
                    )
                ),
            ),
            patch.object(web, "public_address", new=AsyncMock()),
            patch.object(web.store, "connect") as db,
        ):
            result = await web.fetch_product_page(
                "https://www.ithome.com/0/123/456.htm", "拯救者Y9000P"
            )
        self.assertTrue(result["model_match"])
        self.assertEqual(result["evidence_type"], "fetched_third_party_page")
        self.assertEqual(result["published_at"], "2025-08-01")
        self.assertEqual(len(result["images"]), 1)
        self.assertNotIn("官网", result["images"][0]["alt"])
        db.assert_called_once()

    async def test_edifier_gallery_is_parsed_as_data(self):
        import json

        fragment = '<img src="https://cn-oss.edifier.com/product.png">'
        html = (
            "<title>W820NB</title><script>var colorarr = "
            + json.dumps([fragment])
            + "; never_execute();</script>"
        ).encode()
        with (
            patch.object(
                web,
                "fetch_public",
                new=AsyncMock(
                    return_value=(
                        "https://www.edifier.com/cn/product/a.html",
                        {"content-type": "text/html"},
                        html,
                    )
                ),
            ),
            patch.object(web, "public_address", new=AsyncMock()),
            patch.object(web.store, "connect"),
        ):
            result = await web.fetch_product_page(
                "https://www.edifier.com/cn/product/a.html", "W820NB 三金标版"
            )
        self.assertEqual(len(result["images"]), 1)
        self.assertIn("W820NB", result["images"][0]["alt"])
        self.assertNotIn("三金标", result["images"][0]["alt"])

    async def test_verification_page_is_blocked(self):
        html = "<title>安全验证</title>".encode()
        with patch.object(
            web,
            "fetch_public",
            new=AsyncMock(
                return_value=("https://item.jd.com/123.html", {"content-type": "text/html"}, html)
            ),
        ):
            result = await web.fetch_product_page("https://item.jd.com/123.html", "Y9000P")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["images"], [])

    async def test_mismatched_page_never_registers_images(self):
        html = b'<title>Y7000P</title><meta property="og:image" content="https://img.example.com/a.jpg">'
        with (
            patch.object(
                web,
                "fetch_public",
                new=AsyncMock(
                    return_value=(
                        "https://item.jd.com/123.html",
                        {"content-type": "text/html"},
                        html,
                    )
                ),
            ),
            patch.object(web.store, "connect") as db,
        ):
            result = await web.fetch_product_page("https://item.jd.com/123.html", "Y9000P")
        self.assertFalse(result["model_match"])
        self.assertEqual(result["images"], [])
        db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
