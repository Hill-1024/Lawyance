"""
模块描述：provider 真实连通性探测的状态码分类、传输异常翻译与请求形状回归测试。

这些用例不发起真实网络请求：它们直接 mock `services.settings_service.requests`，
锁定「探测是否真的发出请求」以及「失败消息是否具体可操作」。
"""

import unittest
from unittest import mock

import requests

from services import settings_service


class _FakeResponse:
    def __init__(self, status_code: int = 200, chunks: list[bytes] | None = None):
        self.status_code = status_code
        self._chunks = list(chunks if chunks is not None else [b"event: message\n"])
        self.closed = False

    def iter_content(self, chunk_size: int = 1):
        yield from self._chunks

    def close(self):
        self.closed = True


LLM_CFG = {"base_url": "https://api.example/v1", "model": "m", "api_key": "sk-x"}
EMBEDDING_CFG = {"base_url": "https://api.example/v1", "model": "embed-1", "api_key": "sk-x"}
SEARXNG_CFG = {
    "base_url": "https://searx.example",
    "cf_client_id": "cf-id",
    "cf_client_secret": "cf-secret",
}
DELI_CFG = {"endpoint": "https://deli.example/api/query", "appid": "app", "secret": "sec"}
QCC_CFG = {
    "endpoint": "https://agent.qcc.com/mcp/company/stream",
    "access_token": "qcc-token",
}


class ProbeContractTests(unittest.TestCase):
    def test_unknown_provider_message_is_unchanged(self):
        result = settings_service.test_provider_connection("not-a-provider")
        self.assertEqual(result, {"provider": "not-a-provider", "ok": False, "message": "未知的 provider: not-a-provider"})

    def test_missing_required_fields_message_is_unchanged(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value={}):
            result = settings_service.test_provider_connection("llm")
        self.assertEqual(result, {"provider": "llm", "ok": False, "message": "缺少配置: base_url, model, api_key"})


class LlmProbeTests(unittest.TestCase):
    def test_success_reports_connection_ok(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=LLM_CFG):
            with mock.patch.object(settings_service.requests, "get", return_value=_FakeResponse(200)) as get_mock:
                result = settings_service.test_provider_connection("llm")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "大模型 (LLM) 连接正常")
        self.assertEqual(get_mock.call_args.args[0], "https://api.example/v1/models")
        self.assertEqual(get_mock.call_args.kwargs["headers"]["Authorization"], "Bearer sk-x")
        self.assertEqual(get_mock.call_args.kwargs["timeout"], settings_service._PROBE_TIMEOUT_SECONDS)

    def test_auth_failure_is_specific(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=LLM_CFG):
            with mock.patch.object(settings_service.requests, "get", return_value=_FakeResponse(401)):
                result = settings_service.test_provider_connection("llm")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "密钥无效或无权限 (HTTP 401)")

    def test_http_error_reports_status(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=LLM_CFG):
            with mock.patch.object(settings_service.requests, "get", return_value=_FakeResponse(500)):
                result = settings_service.test_provider_connection("llm")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "HTTP 500")

    def test_timeout_is_reported(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=LLM_CFG):
            with mock.patch.object(
                settings_service.requests,
                "get",
                side_effect=requests.exceptions.ConnectTimeout("timed out"),
            ):
                result = settings_service.test_provider_connection("llm")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "连接超时")

    def test_dns_failure_is_reported(self):
        error = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool: Max retries exceeded: Failed to resolve 'nope.invalid'"
        )
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=LLM_CFG):
            with mock.patch.object(settings_service.requests, "get", side_effect=error):
                result = settings_service.test_provider_connection("llm")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "无法连接: 域名解析失败")

    def test_provider_key_missing_falls_back_to_active_profile_key(self):
        provider_without_key = {"base_url": "https://api.example/v1", "model": "m"}
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=provider_without_key):
            with mock.patch.object(
                settings_service,
                "_effective_llm_config",
                return_value={"api_key": "sk-profile"},
            ):
                with mock.patch.object(settings_service.requests, "get", return_value=_FakeResponse(200)) as get_mock:
                    result = settings_service.test_provider_connection("llm")
        self.assertTrue(result["ok"])
        self.assertEqual(get_mock.call_args.kwargs["headers"]["Authorization"], "Bearer sk-profile")


class EmbeddingProbeTests(unittest.TestCase):
    def test_success_posts_ping(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=EMBEDDING_CFG):
            with mock.patch.object(settings_service.requests, "post", return_value=_FakeResponse(200)) as post_mock:
                result = settings_service.test_provider_connection("embedding")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "嵌入模型 (Embedding) 连接正常")
        self.assertEqual(post_mock.call_args.args[0], "https://api.example/v1/embeddings")
        self.assertEqual(post_mock.call_args.kwargs["json"], {"model": "embed-1", "input": "ping"})
        self.assertEqual(post_mock.call_args.kwargs["headers"]["Authorization"], "Bearer sk-x")

    def test_missing_model_is_specific(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=EMBEDDING_CFG):
            with mock.patch.object(settings_service.requests, "post", return_value=_FakeResponse(404)):
                result = settings_service.test_provider_connection("embedding")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "接口或模型不存在 (HTTP 404)")

    def test_bad_request_is_specific(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=EMBEDDING_CFG):
            with mock.patch.object(settings_service.requests, "post", return_value=_FakeResponse(422)):
                result = settings_service.test_provider_connection("embedding")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "请求参数被拒绝 (HTTP 422)")


class SearxngProbeTests(unittest.TestCase):
    def test_success_sends_cloudflare_access_headers(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=SEARXNG_CFG):
            with mock.patch.object(settings_service.requests, "get", return_value=_FakeResponse(200)) as get_mock:
                result = settings_service.test_provider_connection("searxng")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "网页检索 (SearXNG) 连接正常")
        self.assertEqual(get_mock.call_args.args[0], "https://searx.example/search")
        self.assertEqual(get_mock.call_args.kwargs["params"], {"q": "ping", "format": "json"})
        headers = get_mock.call_args.kwargs["headers"]
        self.assertEqual(headers["CF-Access-Client-Id"], "cf-id")
        self.assertEqual(headers["CF-Access-Client-Secret"], "cf-secret")

    def test_auth_denied_mentions_cloudflare(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=SEARXNG_CFG):
            with mock.patch.object(settings_service.requests, "get", return_value=_FakeResponse(403)):
                result = settings_service.test_provider_connection("searxng")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "访问被拒绝，请检查 Cloudflare Access 凭据 (HTTP 403)")


class DeliProbeTests(unittest.TestCase):
    def test_success_uses_read_only_search(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=DELI_CFG):
            with mock.patch.object(settings_service.requests, "post", return_value=_FakeResponse(200)) as post_mock:
                result = settings_service.test_provider_connection("deli")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "得理法搜 连接正常")
        self.assertEqual(post_mock.call_args.args[0], "https://deli.example/api/query")
        headers = post_mock.call_args.kwargs["headers"]
        self.assertEqual(headers["appid"], "app")
        self.assertEqual(headers["secret"], "sec")
        body = post_mock.call_args.kwargs["json"]
        self.assertEqual(body["pageSize"], 1)
        self.assertNotIn("delete", str(body).lower())

    def test_auth_failure_is_specific(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=DELI_CFG):
            with mock.patch.object(settings_service.requests, "post", return_value=_FakeResponse(401)):
                result = settings_service.test_provider_connection("deli")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "密钥无效或无权限 (HTTP 401)")


class QccProbeTests(unittest.TestCase):
    def test_success_uses_initialize_handshake(self):
        fake = _FakeResponse(200)
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=QCC_CFG):
            with mock.patch.object(settings_service.requests, "post", return_value=fake) as post_mock:
                result = settings_service.test_provider_connection("qcc")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "企业信息 (企查查) 连接正常")
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["method"], "initialize")
        self.assertNotEqual(payload.get("method"), "tools/call")
        self.assertEqual(post_mock.call_args.kwargs["headers"]["Authorization"], "Bearer qcc-token")
        self.assertTrue(fake.closed)

    def test_auth_failure_is_specific(self):
        with mock.patch.object(settings_service, "get_provider_runtime_config", return_value=QCC_CFG):
            with mock.patch.object(settings_service.requests, "post", return_value=_FakeResponse(403)):
                result = settings_service.test_provider_connection("qcc")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "访问令牌无效或无权限 (HTTP 403)")


if __name__ == "__main__":
    unittest.main()
