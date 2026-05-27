"""
模块描述：SearXNG 联网搜索和网页正文抓取工具测试。
"""

from __future__ import annotations

import json
import os
import socket
import unittest
from unittest import mock

os.environ.setdefault("DELI_APPID", "test-deli-app")
os.environ.setdefault("DELI_SECRET", "test-deli-secret")
os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")


class _FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status_code = status_code
        self.encoding = "utf-8"
        self.closed = False

    def iter_content(self, chunk_size=65536):
        del chunk_size
        yield self.body

    def close(self):
        self.closed = True


def _fetch_response(url, body, *, status_code=200, content_type="text/html; charset=utf-8"):
    from mcp.searxng_client import FetchResponse

    return FetchResponse(
        url=url,
        final_url=url,
        status_code=status_code,
        headers={"content-type": content_type, "content-length": str(len(body))},
        body=body.encode("utf-8") if isinstance(body, str) else body,
    )


class SearxngToolTests(unittest.TestCase):
    def test_web_search_sends_cf_headers_and_normalizes_results(self):
        from mcp.searxng_client import web_search

        captured = {}

        def fake_get(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return _FakeResponse(json.dumps({
                "number_of_results": 2,
                "results": [
                    {
                        "title": "SearXNG docs",
                        "url": "https://docs.searxng.org/admin/settings.html?token=secret",
                        "content": "Self-hosted metasearch engine " * 40,
                        "engine": "bing",
                        "engines": ["bing", "duckduckgo"],
                        "category": "general",
                        "publishedDate": "2026-05-20T08:30:00Z",
                        "score": 1.0,
                    },
                    {"title": "Ignored by limit", "url": "https://example.com/"},
                ],
                "suggestions": ["searxng docker"],
                "answers": ["drop"],
                "corrections": ["drop"],
                "infoboxes": [{"drop": True}],
                "unresponsive_engines": [],
            }))

        env = {
            "SEARXNG_BASE_URL": "https://serp.example/",
            "SEARXNG_CF_ACCESS_CLIENT_ID": "client-id",
            "SEARXNG_CF_ACCESS_CLIENT_SECRET": "client-secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("mcp.searxng_client.requests.get", side_effect=fake_get):
                result = json.loads(web_search("searxng", limit=1))

        self.assertTrue(result["success"])
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["suggestions"], ["searxng docker"])
        self.assertNotIn("answers", result)
        self.assertNotIn("corrections", result)
        self.assertNotIn("infoboxes", result)
        self.assertEqual(result["results"][0]["rank"], 1)
        self.assertEqual(result["results"][0]["source_domain"], "searxng.org")
        self.assertEqual(result["results"][0]["engines"], ["bing", "duckduckgo"])
        self.assertEqual(result["results"][0]["category"], "general")
        self.assertEqual(result["results"][0]["published_date"], "2026-05-20T08:30:00Z")
        self.assertLessEqual(len(result["results"][0]["snippet"]), 500)
        self.assertNotIn("engine", result["results"][0])
        self.assertNotIn("content", result["results"][0])
        self.assertEqual(captured["url"], "https://serp.example/search")
        self.assertEqual(captured["params"]["q"], "searxng")
        self.assertEqual(captured["params"]["format"], "json")
        self.assertEqual(captured["params"]["language"], "all")
        self.assertEqual(captured["params"]["safesearch"], 0)
        self.assertEqual(captured["params"]["pageno"], 1)
        self.assertNotIn("time_range", captured["params"])
        self.assertEqual(captured["headers"]["CF-Access-Client-Id"], "client-id")
        self.assertEqual(captured["headers"]["CF-Access-Client-Secret"], "client-secret")

    def test_web_search_reports_config_error_for_missing_access_token(self):
        from mcp.searxng_client import web_search

        with mock.patch.dict(os.environ, {"SEARXNG_CF_ACCESS_CLIENT_ID": "client-id"}, clear=True):
            result = json.loads(web_search("searxng"))

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "CONFIG_ERROR")
        self.assertIn("配置不完整", result["error_message"])

    def test_web_search_reports_access_denied_without_leaking_body(self):
        from mcp.searxng_client import web_search

        env = {
            "SEARXNG_CF_ACCESS_CLIENT_ID": "client-id",
            "SEARXNG_CF_ACCESS_CLIENT_SECRET": "client-secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("mcp.searxng_client.requests.get", return_value=_FakeResponse("<html>secret</html>", 403)):
                result = json.loads(web_search("searxng"))

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "AUTH_FAILED")
        self.assertEqual(result["status_code"], 403)
        self.assertNotIn("secret", json.dumps(result, ensure_ascii=False))

    def test_web_search_empty_results_are_successful(self):
        from mcp.searxng_client import web_search

        env = {
            "SEARXNG_CF_ACCESS_CLIENT_ID": "client-id",
            "SEARXNG_CF_ACCESS_CLIENT_SECRET": "client-secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("mcp.searxng_client.requests.get", return_value=_FakeResponse(json.dumps({"results": []}))):
                result = json.loads(web_search("unlikely query"))

        self.assertTrue(result["success"])
        self.assertEqual(result["result_count"], 0)
        self.assertEqual(result["results"], [])

    def test_web_search_reports_all_engines_failed(self):
        from mcp.searxng_client import web_search

        env = {
            "SEARXNG_CF_ACCESS_CLIENT_ID": "client-id",
            "SEARXNG_CF_ACCESS_CLIENT_SECRET": "client-secret",
        }
        body = {"results": [], "unresponsive_engines": ["bing timeout", "duckduckgo timeout"]}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("mcp.searxng_client.requests.get", return_value=_FakeResponse(json.dumps(body))):
                result = json.loads(web_search("query", engines="bing,duckduckgo"))

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "ALL_ENGINES_FAILED")
        self.assertEqual(result["unresponsive_engines"], ["bing timeout", "duckduckgo timeout"])

    def test_web_search_categories_do_not_inherit_default_engines(self):
        from mcp.searxng_client import web_search

        captured = {}

        def fake_get(_url, **kwargs):
            captured.update(kwargs)
            return _FakeResponse(json.dumps({"results": []}))

        env = {
            "SEARXNG_CF_ACCESS_CLIENT_ID": "client-id",
            "SEARXNG_CF_ACCESS_CLIENT_SECRET": "client-secret",
            "SEARXNG_ENGINES": "bing,duckduckgo",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("mcp.searxng_client.requests.get", side_effect=fake_get):
                web_search("OpenAI latest announcement", categories="news")

        self.assertEqual(captured["params"]["categories"], "news")
        self.assertNotIn("engines", captured["params"])

    def test_web_search_dispatches_through_mcps(self):
        import mcps

        def fake_get(_url, **_kwargs):
            return _FakeResponse(json.dumps({"results": [{"title": "Result", "url": "https://example.com"}]}))

        env = {
            "SEARXNG_BASE_URL": "http://127.0.0.1:8080",
            "SEARXNG_CF_ACCESS_CLIENT_ID": "client-id",
            "SEARXNG_CF_ACCESS_CLIENT_SECRET": "client-secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("mcp.searxng_client.requests.get", side_effect=fake_get):
                result = json.loads(mcps.use_tools("web_search", {"query": "lawver"}, conv_id="tester/conv"))

        self.assertTrue(result["success"])
        self.assertEqual(result["results"][0]["title"], "Result")


class WebFetchToolTests(unittest.TestCase):
    def test_web_fetch_extracts_html_and_marks_untrusted_content(self):
        from mcp.searxng_client import web_fetch

        html = "<html><head><title>Story</title></head><body><article>ignored raw</article></body></html>"
        with mock.patch("mcp.searxng_client._fetch_with_redirects", return_value=_fetch_response("https://example.com/a", html)):
            with mock.patch("mcp.searxng_client.trafilatura.extract", return_value="Extracted article body"):
                result = json.loads(web_fetch("https://example.com/a"))

        self.assertTrue(result["success"])
        self.assertEqual(result["title"], "Story")
        self.assertEqual(result["source_domain"] if "source_domain" in result else "example.com", "example.com")
        self.assertIn("BEGIN UNTRUSTED WEB CONTENT", result["text"])
        self.assertIn("Extracted article body", result["text"])
        self.assertFalse(result["truncated"])

    def test_web_fetch_truncates_text_with_marker(self):
        from mcp.searxng_client import web_fetch

        with mock.patch("mcp.searxng_client._fetch_with_redirects", return_value=_fetch_response("https://example.com/a", "hello")):
            with mock.patch("mcp.searxng_client.trafilatura.extract", return_value="abcdef" * 20):
                result = json.loads(web_fetch("https://example.com/a", max_chars=40))

        self.assertTrue(result["success"])
        self.assertTrue(result["truncated"])
        self.assertIn("content truncated", result["text"])
        self.assertEqual(result["text_length"], 120)

    def test_web_fetch_blocks_ssrf_after_dns_resolution(self):
        from mcp.searxng_client import web_fetch

        private_record = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        with mock.patch("mcp.searxng_client.socket.getaddrinfo", return_value=[private_record]):
            result = json.loads(web_fetch("http://localtest.me/"))

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "SSRF_BLOCKED")

    def test_web_fetch_rejects_protocol_downgrade(self):
        from mcp.searxng_client import web_fetch

        with mock.patch("mcp.searxng_client._fetch_with_redirects", side_effect=PermissionError("PROTOCOL_DOWNGRADE")):
            result = json.loads(web_fetch("https://example.com/"))

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "PROTOCOL_DOWNGRADE")

    def test_web_fetch_rejects_unsupported_content_type_and_redacts_url(self):
        from mcp.searxng_client import web_fetch

        response = _fetch_response(
            "https://example.com/file.pdf?token=secret",
            b"%PDF",
            content_type="application/pdf",
        )
        with mock.patch("mcp.searxng_client._fetch_with_redirects", return_value=response):
            result = json.loads(web_fetch("https://example.com/file.pdf?token=secret"))

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "UNSUPPORTED_CONTENT_TYPE")
        self.assertIn("token=%3Credacted%3E", result["url"])
        self.assertNotIn("secret", json.dumps(result, ensure_ascii=False))

    def test_web_fetch_warns_for_likely_spa_shell(self):
        from mcp.searxng_client import web_fetch

        html = "<html><head><title>App</title></head><body><div id='root'></div>" + (" " * 6000) + "</body></html>"
        with mock.patch("mcp.searxng_client._fetch_with_redirects", return_value=_fetch_response("https://example.com/app", html)):
            with mock.patch("mcp.searxng_client.trafilatura.extract", return_value="tiny"):
                result = json.loads(web_fetch("https://example.com/app"))

        self.assertTrue(result["success"])
        self.assertIn("JS-rendered", result["warning"])

    def test_web_fetch_dispatches_through_mcps(self):
        import mcps

        with mock.patch("mcp.searxng_client._fetch_with_redirects", return_value=_fetch_response("https://example.com/a", "plain text", content_type="text/plain")):
            result = json.loads(mcps.use_tools("web_fetch", {"url": "https://example.com/a"}, conv_id="tester/conv"))

        self.assertTrue(result["success"])
        self.assertIn("plain text", result["text"])


if __name__ == "__main__":
    unittest.main()
