"""分流核心（deploy/router）的路由分派、维护兜底与转发保真的回归测试。

用 MockTransport 造两个假上游，直接驱动核心的 ASGI 应用：不监听端口、不碰网络，
也不需要真的功能页/介绍页进程。真实端到端（进程被杀的整条链路）由本机彩排覆盖。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from deploy.router import router as core


def _streamed(
    body: bytes, *, status: int = 200, headers: list[tuple[str, str]] | None = None
) -> httpx.Response:
    """构造一个「异步流式」的假响应。

    必须走异步流：httpx 把同步流（例如直接给 bytes）视为已消费，aiter_raw() 会抛
    StreamConsumed——真实的网络传输走的就是异步流，这里保持同样的形状。
    """

    async def chunks():
        yield body

    return httpx.Response(status, headers=headers or [], content=chunks())


class FakeUpstreams:
    """两个假上游：按端口区分，记录收到的请求，可模拟下线与流式响应。"""

    def __init__(self, app_port: int, intro_port: int):
        self.app_port = app_port
        self.intro_port = intro_port
        self.app_down = False
        self.intro_down = False
        self.app_read_error = False
        self.seen: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _side(self, request: httpx.Request) -> str:
        return "app" if request.url.port == self.app_port else "intro"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        side = self._side(request)
        if (side == "app" and self.app_down) or (side == "intro" and self.intro_down):
            raise httpx.ConnectError(f"{side} is down", request=request)
        if side == "app" and self.app_read_error:
            # 上游接受连接后、回完响应头之前被 RST：httpx 抛 ReadError。
            raise httpx.ReadError(f"{side} reset while reading response headers", request=request)
        if request.url.path == "/api/court/turn":
            chunks = [b'data: {"n": 1}\n\n', b'data: {"n": 2}\n\n', b"data: [DONE]\n\n"]

            async def events():
                for chunk in chunks:
                    yield chunk

            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=events()
            )
        if request.url.path == "/api/cookies":
            return _streamed(
                b'{"ok": true}',
                headers=[
                    ("content-type", "application/json"),
                    ("set-cookie", "a=1; Path=/"),
                    ("set-cookie", "b=2; Path=/"),
                ],
            )
        return _streamed(
            json.dumps(
                {"side": side, "path": request.url.path, "query": request.url.query.decode()}
            ).encode(),
            headers=[("content-type", "application/json")],
        )


class RouterTestCase(unittest.IsolatedAsyncioTestCase):
    APP_PORT = 18081
    INTRO_PORT = 18082

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.upstreams = FakeUpstreams(self.APP_PORT, self.INTRO_PORT)
        self.core = core.Core(
            core.Config(
                app_upstream=f"http://127.0.0.1:{self.APP_PORT}",
                intro_upstream=f"http://127.0.0.1:{self.INTRO_PORT}",
                state_dir=self.tmp.name,
                maintenance_page=str(Path(core.__file__).resolve().parent / "maintenance.html"),
            ),
            transport=self.upstreams.transport(),
        )
        app = core.create_app(core=self.core)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://lawver.dev"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.core.aclose()
        self.tmp.cleanup()

    # ── 分派 ──────────────────────────────────────────────────────────────
    async def test_paths_are_split_between_sides(self):
        cases = (
            ("/", "intro"),
            ("/design", "intro"),
            ("/pricing/", "intro"),
            ("/download", "intro"),
            ("/robots.txt", "intro"),
            ("/sitemap.xml", "intro"),
            ("/intro-assets/index-abc.js", "intro"),
            ("/home", "app"),
            ("/login", "app"),
            ("/settings/profile", "app"),
            ("/court/abc", "app"),
            ("/api/plans", "app"),
            ("/manifest.webmanifest", "app"),
            ("/designer", "app"),
            ("/pricing/legacy", "app"),
        )
        for path, expected in cases:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(200, response.status_code)
                self.assertEqual(expected, response.headers["x-core-upstream"])

    async def test_query_string_is_forwarded(self):
        response = await self.client.get("/court/new?project=p1")
        self.assertEqual(200, response.status_code)
        self.assertEqual("project=p1", response.json()["query"])

    # ── 维护兜底 ───────────────────────────────────────────────────────────
    async def test_navigation_redirects_to_maintenance_page(self):
        self.upstreams.app_down = True
        await self.core.probe_once()
        response = await self.client.get(
            "/home", headers={"sec-fetch-mode": "navigate", "accept": "text/html"}
        )
        self.assertEqual(302, response.status_code)
        self.assertEqual("/under_maintenance?from=%2Fhome", response.headers["location"])
        self.assertEqual("no-store", response.headers["cache-control"])

    async def test_redirect_keeps_the_original_query(self):
        self.upstreams.app_down = True
        await self.core.probe_once()
        response = await self.client.get(
            "/court/new?project=p1", headers={"sec-fetch-mode": "navigate"}
        )
        self.assertEqual(302, response.status_code)
        self.assertEqual(
            "/under_maintenance?from=%2Fcourt%2Fnew%3Fproject%3Dp1", response.headers["location"]
        )

    async def test_api_requests_get_503_json_instead_of_a_redirect(self):
        self.upstreams.app_down = True
        await self.core.probe_once()
        response = await self.client.get(
            "/api/plans", headers={"sec-fetch-mode": "cors", "accept": "application/json"}
        )
        self.assertEqual(503, response.status_code)
        self.assertEqual("30", response.headers["retry-after"])
        payload = response.json()
        self.assertEqual("maintenance", payload["status"])
        self.assertEqual("app", payload["side"])

    async def test_static_assets_never_receive_html(self):
        self.upstreams.intro_down = True
        await self.core.probe_once()
        response = await self.client.get(
            "/intro-assets/index-abc.js", headers={"sec-fetch-mode": "no-cors", "accept": "*/*"}
        )
        self.assertEqual(503, response.status_code)
        self.assertNotIn("text/html", response.headers.get("content-type", ""))

    async def test_intro_and_app_are_independent(self):
        self.upstreams.intro_down = True
        await self.core.probe_once()
        self.assertEqual(
            302,
            (await self.client.get("/", headers={"sec-fetch-mode": "navigate"})).status_code,
        )
        self.assertEqual(200, (await self.client.get("/home")).status_code)
        self.upstreams.intro_down = False
        self.upstreams.app_down = True
        await self.core.probe_once()
        self.assertEqual(200, (await self.client.get("/")).status_code)
        self.assertEqual(
            302,
            (await self.client.get("/home", headers={"sec-fetch-mode": "navigate"})).status_code,
        )

    async def test_maintenance_page_is_self_contained(self):
        self.upstreams.app_down = True
        await self.core.probe_once()
        response = await self.client.get("/under_maintenance?from=%2Fpricing")
        self.assertEqual(200, response.status_code)
        self.assertEqual("noindex", response.headers["x-robots-tag"])
        body = response.text
        self.assertIn("维护中", body)
        self.assertIn("我们很快就会回来", body)
        self.assertIn("工作台", body)
        self.assertIn('"/pricing"', body)
        self.assertIn("/__core/status", body)
        self.assertNotIn("__SIDE_LABEL__", body)
        self.assertNotIn("__RETRY_MS__", body)
        # 两侧都下线时这个页面也要能打开，所以不能有任何外链资源。
        self.assertNotIn("https://", body)
        self.assertNotIn("http://", body)

    async def test_maintenance_page_escapes_from_for_script_context(self):
        """from 是不可信输入：</script> 不能提前闭合脚本标签。"""
        # 以 / 开头（能通过站内路径校验）但内嵌 </script> 的载荷，考验转义层。
        payload = "%2F%3C%2Fscript%3E%3Cscript%3Ealert(1)%3C%2Fscript%3E"
        response = await self.client.get(f"/under_maintenance?from={payload}")
        body = response.text
        # JSON 字面量里的 < > & 必须以 \\uXXXX 出现，而不是裸字符。
        self.assertNotIn("<script>alert(1)", body)
        self.assertIn('var FROM = "/\\u003c/script\\u003e\\u003cscript\\u003e', body)
        # 站内路径原样保留（JSON 层），恢复后能回跳。
        ok = await self.client.get("/under_maintenance?from=%2Fcourt%2Fnew")
        self.assertIn('"/court/new"', ok.text)

    async def test_maintenance_page_only_accepts_site_local_from(self):
        """from 必须是以单个 / 开头的站内路径，站外地址一律回退到 /。"""
        for evil in (
            "https%3A%2F%2Fevil.com",
            "%2F%2Fevil.com",
            "%2F%5Cevil.com",
            "javascript%3Aalert(1)",
        ):
            response = await self.client.get(f"/under_maintenance?from={evil}")
            self.assertIn('var FROM = ""', response.text, evil)
        ok = await self.client.get("/under_maintenance?from=%2Fcourt%2Fnew%3Fproject%3Dp1")
        self.assertIn('"/court/new?project=p1"', ok.text)

    async def test_planned_maintenance_flag_covers_both_directions(self):
        flag = Path(self.tmp.name) / "app.maintenance"
        flag.write_text("", encoding="utf-8")
        await self.core.probe_once()
        self.assertFalse(self.core.sides["app"].up)
        self.assertEqual(
            302,
            (await self.client.get("/home", headers={"sec-fetch-mode": "navigate"})).status_code,
        )
        self.assertEqual(200, (await self.client.get("/")).status_code)
        flag.unlink()
        await self.core.probe_once()
        self.assertTrue(self.core.sides["app"].up)
        self.assertEqual(200, (await self.client.get("/home")).status_code)

    async def test_status_endpoint_reports_both_sides(self):
        payload = (await self.client.get("/__core/status")).json()
        self.assertEqual("ok", payload["status"])
        self.assertEqual({"app", "intro"}, set(payload["sides"]))
        self.assertEqual("/api/health", payload["sides"]["app"]["probe"])
        self.upstreams.intro_down = True
        await self.core.probe_once()
        payload = (await self.client.get("/__core/status")).json()
        self.assertEqual("maintenance", payload["status"])
        self.assertFalse(payload["sides"]["intro"]["up"])
        self.assertTrue(payload["sides"]["app"]["up"])

    # ── 被动判下线与恢复 ───────────────────────────────────────────────────
    async def test_connect_error_marks_the_side_down_instead_of_502(self):
        self.upstreams.app_down = True  # 状态还认为在线：没有 probe 过
        response = await self.client.get("/home", headers={"sec-fetch-mode": "navigate"})
        self.assertEqual(302, response.status_code)
        self.assertFalse(self.core.sides["app"].up)
        self.upstreams.app_down = False
        await self.core.probe_once()
        self.assertEqual(200, (await self.client.get("/home")).status_code)

    async def test_read_error_while_reading_headers_marks_the_side_down_instead_of_500(self):
        # 上游接受连接后在读响应头阶段断开（ReadError）：同样要立刻判下线给维护页，
        # 而不是把异常冒成 500、再等最多一个探活周期才恢复。
        self.upstreams.app_read_error = True
        response = await self.client.get("/home", headers={"sec-fetch-mode": "navigate"})
        self.assertEqual(302, response.status_code)
        self.assertFalse(self.core.sides["app"].up)
        self.upstreams.app_read_error = False
        await self.core.probe_once()
        self.assertEqual(200, (await self.client.get("/home")).status_code)

    # ── 转发保真 ───────────────────────────────────────────────────────────
    async def test_sse_stream_passes_through_unbuffered(self):
        response = await self.client.get("/api/court/turn")
        self.assertEqual(200, response.status_code)
        self.assertEqual("text/event-stream", response.headers["content-type"])
        self.assertNotIn("content-length", response.headers)
        self.assertEqual(3, response.text.count("data:"))
        self.assertIn("[DONE]", response.text)

    async def test_body_headers_and_cookies_are_forwarded(self):
        payload = bytes(range(256)) * 8
        response = await self.client.post(
            "/api/upload",
            content=payload,
            headers={
                "cookie": "auth_token=abc",
                "cf-connecting-ip": "203.0.113.7",
                "content-type": "application/octet-stream",
            },
        )
        self.assertEqual(200, response.status_code)
        upstream = self.upstreams.seen[-1]
        self.assertEqual(payload, upstream.content)
        self.assertEqual("auth_token=abc", upstream.headers["cookie"])
        self.assertEqual("203.0.113.7", upstream.headers["cf-connecting-ip"])
        # Host 必须改写为上游自己的地址，否则功能页会按外部域名判断来源。
        self.assertEqual(f"127.0.0.1:{self.APP_PORT}", upstream.headers["host"])

    async def test_downstream_set_cookie_headers_are_preserved(self):
        response = await self.client.get("/api/cookies")
        self.assertEqual(200, response.status_code)
        self.assertEqual(["a=1; Path=/", "b=2; Path=/"], response.headers.get_list("set-cookie"))


if __name__ == "__main__":
    unittest.main()
