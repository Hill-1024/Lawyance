"""自营法库客户端契约、失败策略与三工具兼容性回归测试。"""

import json
import os
import unittest
from unittest import mock

import requests

from mcp import law_service_client, pkulaw_client


REMOTE_ENV = {
    "LAWVER_LAW_SOURCE": "remote",
    "LAWVER_LAW_SERVICE_URL": "https://law.example.test/prefix/",
    "LAWVER_LAW_SERVICE_KEY": "lvk_test-secret",
    "LAWVER_LAW_SERVICE_TIMEOUT": "10",
    "PKU_LAW_SOURCE": "",
}
ARTICLE = {
    "law_name": "测试法",
    "article_number": "第一条",
    "content": "测试正文" * 100,
    "url": "https://example.test/law/1",
}


class FakeResponse:
    def __init__(self, payload=None, *, status=200, body=None):
        self.status_code = status
        self.body = body if body is not None else json.dumps(payload).encode()
        self.closed = False

    def iter_content(self, chunk_size):
        yield self.body

    def close(self):
        self.closed = True


class LawServiceTransportTests(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, REMOTE_ENV)
        env.start()
        self.addCleanup(env.stop)

    def test_three_raw_contracts_and_bearer_timeout_are_preserved(self):
        cases = [
            (law_service_client.law_exact_search, ("测试法", "第一条"), "exact", {"title": "测试法", "number": "第一条"}, {"success": True, "data": ARTICLE}),
            (law_service_client.law_fuzzy_search, ("检索词", 5), "search", {"query": "检索词", "limit": 5}, {"success": True, "data": [ARTICLE]}),
            (law_service_client.law_link_search, ("《测试法》第一条", 5), "links", {"text": "《测试法》第一条", "limit": 5}, {"success": True, "text": "链接正文"}),
        ]
        for function, args, suffix, body, result in cases:
            with self.subTest(suffix=suffix):
                response = FakeResponse(result)
                with mock.patch.object(law_service_client.requests, "post", return_value=response) as post:
                    self.assertEqual(json.loads(function(*args)), result)
                post.assert_called_once_with(
                    f"https://law.example.test/prefix/v1/laws/{suffix}",
                    json=body,
                    headers={"Authorization": "Bearer lvk_test-secret", "Accept": "application/json"},
                    timeout=(3.0, 10.0),
                    allow_redirects=False,
                    stream=True,
                )
                self.assertTrue(response.closed)

    def test_local_http_and_custom_positive_timeout_are_supported(self):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            with self.subTest(host=host):
                with mock.patch.dict(os.environ, {"LAWVER_LAW_SERVICE_URL": f"http://{host}:8084", "LAWVER_LAW_SERVICE_TIMEOUT": "1.5"}):
                    with mock.patch.object(law_service_client.requests, "post", return_value=FakeResponse({"success": False, "message": "未找到"})) as post:
                        law_service_client.law_exact_search("测试法", "第一条")
                self.assertEqual(post.call_args.kwargs["timeout"], (1.5, 1.5))

    def test_http_non_loopback_is_rejected_without_network_or_secret_echo(self):
        for host in ("law.example.test", "203.0.113.10", "192.168.1.20", "law-service", "localhost.example.test", "127.0.0.1.example.test"):
            url = f"http://{host}:8084"
            with self.subTest(host=host), mock.patch.dict(os.environ, {"LAWVER_LAW_SERVICE_URL": url}):
                with mock.patch.object(law_service_client.requests, "post") as post:
                    with self.assertRaisesRegex(law_service_client.LawServiceError, "HTTPS") as caught:
                        law_service_client.law_exact_search("测试法", "第一条")
                    result = json.loads(pkulaw_client.get_article("测试法", "第一条"))
                self.assertFalse(result["success"])
                self.assertNotIn(REMOTE_ENV["LAWVER_LAW_SERVICE_KEY"], str(caught.exception))
                self.assertNotIn(REMOTE_ENV["LAWVER_LAW_SERVICE_KEY"], result["message"])
                self.assertNotIn(url, str(caught.exception))
                post.assert_not_called()

    def test_remote_queries_use_the_existing_local_engine_input_limits(self):
        cases = [
            (law_service_client.law_exact_search, ("名" * 201, "号" * 65), {"title": "名" * 160, "number": "号" * 40}),
            (law_service_client.law_fuzzy_search, ("词" * 8001,), {"query": "词" * 4000, "limit": 5}),
            (law_service_client.law_link_search, ("文" * 8001,), {"text": "文" * 4000, "limit": 5}),
        ]
        for function, args, body in cases:
            with self.subTest(function=function.__name__):
                with mock.patch.object(law_service_client.requests, "post", return_value=FakeResponse({"success": False, "message": "未找到"})) as post:
                    function(*args)
                self.assertEqual(post.call_args.kwargs["json"], body)

    def test_bad_configuration_never_sends_a_request(self):
        cases = [
            {"LAWVER_LAW_SERVICE_URL": ""},
            {"LAWVER_LAW_SERVICE_KEY": ""},
            *({"LAWVER_LAW_SERVICE_URL": value} for value in (
                "file:///tmp/law", "law.example.test", "https://user:secret@law.test",
                "https://law.test?token=secret", "https://law.test#secret", "http://law.test:bad", "https://law.test:0", "https://law. test",
            )),
            *({"LAWVER_LAW_SERVICE_TIMEOUT": value} for value in ("bad", "0", "-1", "nan", "inf")),
            {"LAWVER_LAW_SERVICE_KEY": "Bearer lvk_secret"},
        ]
        for config in cases:
            with self.subTest(config=config), mock.patch.dict(os.environ, config):
                with mock.patch.object(law_service_client.requests, "post") as post:
                    with self.assertRaises(law_service_client.LawServiceError):
                        law_service_client.law_exact_search("测试法", "第一条")
                post.assert_not_called()

    def test_transient_network_and_server_errors_retry_once_then_recover(self):
        for failure in (requests.Timeout("private query"), requests.ConnectionError("secret"), *(FakeResponse(status=status) for status in (500, 502, 503, 504))):
            with self.subTest(failure=type(failure).__name__):
                success = FakeResponse({"success": True, "data": ARTICLE})
                with mock.patch.object(law_service_client.requests, "post", side_effect=[failure, success]) as post:
                    self.assertTrue(json.loads(law_service_client.law_exact_search("测试法", "第一条"))["success"])
                self.assertEqual(post.call_count, 2)
                self.assertTrue(success.closed)
                if isinstance(failure, FakeResponse):
                    self.assertTrue(failure.closed)

    def test_repeated_failures_stop_after_two_attempts(self):
        for failure in (requests.Timeout("lvk_secret in URL"), requests.ConnectionError("private query")):
            with mock.patch.object(law_service_client.requests, "post", side_effect=failure) as post:
                with self.assertRaises(law_service_client.LawServiceError) as caught:
                    law_service_client.law_exact_search("测试法", "第一条")
            self.assertEqual(post.call_count, 2)
            self.assertNotIn("lvk_secret", str(caught.exception))
            self.assertNotIn("private query", str(caught.exception))
        responses = [FakeResponse(status=503), FakeResponse(status=503)]
        with mock.patch.object(law_service_client.requests, "post", side_effect=responses) as post:
            with self.assertRaisesRegex(law_service_client.LawServiceError, "503"):
                law_service_client.law_exact_search("测试法", "第一条")
        self.assertEqual(post.call_count, 2)
        self.assertTrue(all(response.closed for response in responses))

    def test_auth_rate_limit_redirect_and_client_errors_are_not_retried(self):
        for status in (301, 400, 401, 403, 404, 429):
            with self.subTest(status=status):
                response = FakeResponse(status=status, body=b"private query lvk_secret")
                with mock.patch.object(law_service_client.requests, "post", return_value=response) as post:
                    with self.assertRaisesRegex(law_service_client.LawServiceError, str(status)) as caught:
                        law_service_client.law_exact_search("测试法", "第一条")
                self.assertNotIn("lvk_secret", str(caught.exception))
                post.assert_called_once()
                self.assertTrue(response.closed)

    def test_malformed_and_oversized_responses_are_not_retried(self):
        for response in (
            FakeResponse(body=b"not json"), FakeResponse([]), FakeResponse({"success": "yes"}),
            FakeResponse({"success": True, "data": []}),
            FakeResponse({"success": True, "data": {"content": 42}}),
            FakeResponse(body=b"x" * (law_service_client._MAX_RESPONSE_BYTES + 1)),
        ):
            with mock.patch.object(law_service_client.requests, "post", return_value=response) as post:
                with self.assertRaises(law_service_client.LawServiceError):
                    law_service_client.law_exact_search("测试法", "第一条")
            post.assert_called_once()
            self.assertTrue(response.closed)


class LawServiceToolCompatibilityTests(unittest.TestCase):
    def test_three_tools_produce_identical_local_and_remote_outputs(self):
        local_engine = mock.Mock()
        local_engine.law_exact_search.return_value = json.dumps({"success": True, "data": ARTICLE})
        local_engine.law_fuzzy_search.return_value = json.dumps({"success": True, "data": [ARTICLE]})
        local_engine.law_link_search.return_value = json.dumps({"success": True, "text": "法律依据链接"})
        calls = [(pkulaw_client.get_article, ("测试法", "第一条")), (pkulaw_client.search_article, ("测试",)), (pkulaw_client.get_linked_content, ("《测试法》第一条",))]
        raw = [json.loads(local_engine.law_exact_search.return_value), json.loads(local_engine.law_fuzzy_search.return_value), json.loads(local_engine.law_link_search.return_value)]
        with mock.patch.dict(os.environ, {"LAWVER_LAW_SOURCE": "local", "PKU_LAW_SOURCE": "remote"}):
            with mock.patch.object(pkulaw_client, "_local_search_engine", return_value=local_engine):
                local = [function(*args) for function, args in calls]
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(law_service_client.requests, "post", side_effect=[FakeResponse(payload) for payload in raw]):
                with mock.patch.object(pkulaw_client, "_local_search_engine") as local_import:
                    remote = [function(*args) for function, args in calls]
        self.assertEqual(local, remote)
        self.assertIn("...", json.loads(remote[1])["result"])
        local_import.assert_not_called()

    def test_explicit_source_overrides_legacy_pkulaw_and_uses_no_rag(self):
        with mock.patch.dict(os.environ, {**REMOTE_ENV, "PKU_LAW_SOURCE": "remote"}):
            with mock.patch.object(law_service_client.requests, "post", return_value=FakeResponse({"success": True, "data": ARTICLE})):
                with mock.patch.object(pkulaw_client, "_remote_client") as pku, mock.patch.object(pkulaw_client, "_local_search_engine") as local:
                    self.assertTrue(json.loads(pkulaw_client.get_article("测试法", "第一条"))["success"])
                    self.assertEqual(pkulaw_client.ensure_law_database_ready()["mode"], "remote")
        pku.assert_not_called()
        local.assert_not_called()

    def test_unset_source_keeps_legacy_selection_and_ignores_stale_url(self):
        with mock.patch.dict(os.environ, {**REMOTE_ENV, "LAWVER_LAW_SOURCE": "", "PKU_LAW_SOURCE": "remote"}):
            self.assertTrue(pkulaw_client._remote_enabled())
        local = mock.Mock()
        local.law_fuzzy_search.return_value = json.dumps({"success": True, "data": [ARTICLE]})
        with mock.patch.dict(os.environ, {**REMOTE_ENV, "LAWVER_LAW_SOURCE": "", "PKU_LAW_SOURCE": ""}):
            with mock.patch.object(pkulaw_client, "_local_search_engine", return_value=local):
                with mock.patch.object(law_service_client.requests, "post") as post:
                    self.assertTrue(json.loads(pkulaw_client.search_article("测试"))["success"])
            post.assert_not_called()

    def test_remote_errors_remain_structured_without_local_fallback(self):
        for config in ({"LAWVER_LAW_SERVICE_KEY": ""}, {"LAWVER_LAW_SERVICE_URL": ""}, {"LAWVER_LAW_SOURCE": "typo"}):
            with mock.patch.dict(os.environ, {**REMOTE_ENV, **config}):
                with mock.patch.object(pkulaw_client, "_local_search_engine") as local:
                    for function, args in [(pkulaw_client.get_article, ("法", "第一条")), (pkulaw_client.search_article, ("查询",)), (pkulaw_client.get_linked_content, ("《法》第一条",))]:
                        result = json.loads(function(*args))
                        self.assertFalse(result["success"])
                        self.assertIn("LAWVER_LAW_", result["message"])
                local.assert_not_called()

    def test_startup_rejects_missing_remote_configuration_without_import_or_network(self):
        with mock.patch.dict(os.environ, {**REMOTE_ENV, "LAWVER_LAW_SERVICE_KEY": ""}):
            with mock.patch.object(pkulaw_client, "_local_search_engine") as local, mock.patch.object(law_service_client.requests, "post") as post:
                with self.assertRaisesRegex(law_service_client.LawServiceError, "LAWVER_LAW_SERVICE_KEY"):
                    pkulaw_client.ensure_law_database_ready()
        local.assert_not_called()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
