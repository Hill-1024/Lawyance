"""
模块描述：本机/内网目标不经代理的回归测试（本地调试不受系统代理影响）。

开着代理工具（Clash 一类）时，httpx 会读到系统代理却不读绕过列表：指向 127.0.0.1 的
本地模型、分流核心转发到 127.0.0.1:8081 的请求都会被转给代理，常见结果是 502。
这里用「代理环境变量指向一个没人监听的端口」来模拟：走了代理就连不上，直连才能成功。
公网目标必须保持原样（仍然走代理），否则需要代理才能访问的境外模型 API 会被直连坏掉。
"""

import asyncio
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import httpx
import requests

from infra import net


class _LocalService(BaseHTTPRequestHandler):
    """一个本机假服务：/v1/models 与 /v1/embeddings 都回最小合法响应。"""

    def log_message(self, *_args):
        pass

    def _reply(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._reply({"object": "list", "data": [{"id": "local-model", "object": "model", "owned_by": "test"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._reply({"data": [{"index": 0, "embedding": [1.0, 0.0]}]})


def _dead_proxy_env() -> dict:
    """代理指向回环上一个关闭的端口；去掉 NO_PROXY，模拟「没配绕过」的代理环境。"""
    env = {key: value for key, value in os.environ.items() if key.lower() != "no_proxy"}
    env.update({"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": ""})
    return env


class LocalHostClassificationTests(unittest.TestCase):
    def test_local_and_private_hosts(self):
        for host in ("127.0.0.1", "localhost", "api.localhost", "::1", "[::1]", "192.168.1.20",
                     "10.0.0.5", "172.16.3.4", "169.254.1.1", "ollama", "searxng."):
            self.assertTrue(net.is_local_host(host), host)

    def test_public_hosts(self):
        for host in ("api.deepseek.com", "8.8.8.8", "serp.mutsumi.moe", "172.32.0.1", "", None):
            self.assertFalse(net.is_local_host(host), host)

    def test_requests_proxies_only_override_local_targets(self):
        self.assertEqual(
            net.requests_proxies("http://127.0.0.1:11434/v1"),
            {"http": None, "https": None, "all": None},
        )
        self.assertIsNone(net.requests_proxies("https://api.deepseek.com/v1"))
        self.assertIsNone(net.requests_proxies("not a url"))


class LocalProxyBypassTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalService)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_llm_client_reaches_a_local_model_server_directly(self):
        from llm.client import build_client

        async def list_models():
            client = build_client("local-key", self.base + "/v1")
            try:
                return [model.id for model in (await client.models.list()).data]
            finally:
                await client.close()

        with mock.patch.dict(os.environ, _dead_proxy_env(), clear=True):
            self.assertEqual(asyncio.run(list_models()), ["local-model"])

    def test_llm_client_keeps_the_proxy_for_public_endpoints(self):
        from llm.client import build_client

        with mock.patch.dict(os.environ, _dead_proxy_env(), clear=True):
            client = build_client("key", "https://api.example.com/v1")
            transport = client._client._transport_for_url(httpx.URL("https://api.example.com/v1/models"))
            # 公网端点仍走代理（不是默认直连传输），境外模型 API 不会被这次改动直连坏掉。
            self.assertIsNot(transport, client._client._transport)
            asyncio.run(client.close())

    def test_requests_and_urllib_reach_local_services_directly(self):
        with mock.patch.dict(os.environ, _dead_proxy_env(), clear=True):
            url = self.base + "/v1/models"
            self.assertEqual(requests.get(url, timeout=5, proxies=net.requests_proxies(url)).status_code, 200)
            request = urllib.request.Request(self.base + "/v1/embeddings", data=b"{}", method="POST")
            with net.urlopen(request, timeout=5) as response:
                self.assertEqual(json.loads(response.read())["data"][0]["embedding"], [1.0, 0.0])

    def test_router_forwards_to_local_upstreams_directly(self):
        from deploy.router import router as core

        async def probe():
            with tempfile.TemporaryDirectory() as tmp:
                instance = core.Core(
                    core.Config(
                        app_upstream=self.base,
                        intro_upstream=self.base,
                        state_dir=tmp,
                        maintenance_page=str(Path(core.__file__).resolve().parent / "maintenance.html"),
                    )
                )
                try:
                    return (await instance.client.get(self.base + "/api/health")).status_code
                finally:
                    await instance.aclose()

        with mock.patch.dict(os.environ, _dead_proxy_env(), clear=True):
            self.assertEqual(asyncio.run(probe()), 200)


if __name__ == "__main__":
    unittest.main()
