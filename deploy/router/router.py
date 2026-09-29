#!/usr/bin/env python3
"""Lawver 分流核心：一台机器上两个后端（功能页 / 介绍页）的唯一入口。

职责只有三件：
  1. 路径分派——介绍页路径给介绍页进程，其余全部给功能页进程；
  2. 健康感知——被动（转发时连不上）+ 主动（每 5s 探活）；
  3. 维护兜底——某侧下线或处于计划维护时，页面导航 302 到 /under_maintenance，
     接口与静态资源返回 503 JSON。fetch 跟着 302 拿到 HTML 是最难排查的一类故障，
     所以接口一律不重定向。

设计取向：
  · 稳定端口：隧道入口指向这里，之后功能页/介绍页怎么重启换代都不用改入口配置；
  · 不缓冲：SSE 与几十 MB 的上传都必须流式穿透，绝不能整包读进内存；
  · 不猜：探活只看进程活着，数据库抖动由具体接口自己报错，不该被判成整个功能页下线。

用法：
    python deploy/router/router.py --config deploy/router/config.example.json
环境变量（优先级高于配置文件）：LAWVER_ROUTER_HOST/PORT、LAWVER_ROUTER_APP_UPSTREAM、
LAWVER_ROUTER_INTRO_UPSTREAM、LAWVER_ROUTER_STATE_DIR、LAWVER_ROUTER_PROBE_INTERVAL。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

LOG = logging.getLogger("lawver.router")

# ── 路径表 ────────────────────────────────────────────────────────────────
# 介绍页自己的路径；这张表必须与介绍页仓 README 里的表格一致。
DEFAULT_INTRO_EXACT = ("/", "/design", "/download", "/pricing", "/robots.txt", "/sitemap.xml")
DEFAULT_INTRO_PREFIXES = ("/intro-assets/",)
# 核心自己回答的路径：维护页与状态接口，任何一侧下线都要能打开。
CORE_EXACT = ("/under_maintenance",)
CORE_PREFIXES = ("/__core/",)

APP_SIDE = "app"
INTRO_SIDE = "intro"
SIDE_LABELS = {APP_SIDE: "工作台", INTRO_SIDE: "介绍页"}

# 逐跳头不参与转发（RFC 9110 §7.6.1）。
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}
# 上游响应里额外丢掉 content-length：转发是流式的，长度交给 Starlette 决定。
RESPONSE_DROP = HOP_BY_HOP | {"content-length"}


@dataclass
class SideSpec:
    """一侧的静态配置。"""

    name: str
    upstream: str
    probe_path: str
    flag_name: str


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8080
    app_upstream: str = "http://127.0.0.1:8081"
    intro_upstream: str = "http://127.0.0.1:8082"
    state_dir: str = ""
    intro_exact: tuple[str, ...] = DEFAULT_INTRO_EXACT
    intro_prefixes: tuple[str, ...] = DEFAULT_INTRO_PREFIXES
    probe_interval: float = 5.0
    probe_timeout: float = 2.0
    connect_timeout: float = 5.0
    retry_after: int = 30
    maintenance_page: str = ""
    log_level: str = "info"

    @classmethod
    def from_file_and_env(cls, path: str | None) -> "Config":
        data: dict = {}
        if path:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        config = cls(
            host=str(data.get("host") or "127.0.0.1"),
            port=int(data.get("port") or 8080),
            app_upstream=str(data.get("app_upstream") or "http://127.0.0.1:8081"),
            intro_upstream=str(data.get("intro_upstream") or "http://127.0.0.1:8082"),
            state_dir=str(data.get("state_dir") or ""),
            intro_exact=tuple(data.get("intro_exact") or DEFAULT_INTRO_EXACT),
            intro_prefixes=tuple(data.get("intro_prefixes") or DEFAULT_INTRO_PREFIXES),
            probe_interval=float(data.get("probe_interval") or 5.0),
            probe_timeout=float(data.get("probe_timeout") or 2.0),
            connect_timeout=float(data.get("connect_timeout") or 5.0),
            retry_after=int(data.get("retry_after") or 30),
            maintenance_page=str(data.get("maintenance_page") or ""),
            log_level=str(data.get("log_level") or "info"),
        )

        config.host = os.environ.get("LAWVER_ROUTER_HOST", config.host)
        config.port = int(os.environ.get("LAWVER_ROUTER_PORT", config.port))
        config.app_upstream = os.environ.get("LAWVER_ROUTER_APP_UPSTREAM", config.app_upstream)
        config.intro_upstream = os.environ.get("LAWVER_ROUTER_INTRO_UPSTREAM", config.intro_upstream)
        config.state_dir = os.environ.get("LAWVER_ROUTER_STATE_DIR", config.state_dir)
        config.probe_interval = float(
            os.environ.get("LAWVER_ROUTER_PROBE_INTERVAL", config.probe_interval)
        )
        if not config.state_dir:
            config.state_dir = str(Path(__file__).resolve().parent / "state")
        if not config.maintenance_page:
            config.maintenance_page = str(Path(__file__).resolve().parent / "maintenance.html")
        return config


@dataclass
class SideState:
    """一侧的运行时状态。"""

    spec: SideSpec
    up: bool = True
    reason: str = "startup"
    since: float = field(default_factory=time.time)
    last_checked: float = 0.0

    @property
    def planned(self) -> bool:
        """计划维护：开关文件在，就当作这一侧不在服务，不管进程是否活着。"""
        return Path(self.spec.flag_path).exists()


class Core:
    """分派、探活与维护兜底的全部逻辑（不依赖 Starlette，便于直接测）。"""

    def __init__(self, config: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        state_dir = Path(config.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.sides: dict[str, SideState] = {
            APP_SIDE: SideState(
                SideSpec(
                    name=APP_SIDE,
                    upstream=config.app_upstream.rstrip("/"),
                    probe_path="/api/health",
                    flag_name="app.maintenance",
                )
            ),
            INTRO_SIDE: SideState(
                SideSpec(
                    name=INTRO_SIDE,
                    upstream=config.intro_upstream.rstrip("/"),
                    probe_path="/healthz",
                    flag_name="intro.maintenance",
                )
            ),
        }
        for side in self.sides.values():
            side.spec.flag_path = str(state_dir / side.spec.flag_name)
        self.client = httpx.AsyncClient(
            # 读超时不设：模型调用要跑几分钟，超时会被误判成故障。
            timeout=httpx.Timeout(
                connect=config.connect_timeout, read=None, write=None, pool=None
            ),
            transport=transport,
            follow_redirects=False,
        )
        self.page_template = Path(config.maintenance_page).read_text(encoding="utf-8")

    # ── 分派 ───────────────────────────────────────────────────────────────
    def route_of(self, path: str) -> str:
        """返回 core / intro / app。"""
        if path in CORE_EXACT or any(path.startswith(p) for p in CORE_PREFIXES):
            return "core"
        # 尾斜杠不影响归属：/pricing/ 与 /pricing 是同一个页面。
        normalized = path.rstrip("/") or "/"
        if normalized in self.config.intro_exact or any(
            path.startswith(p) for p in self.config.intro_prefixes
        ):
            return INTRO_SIDE
        return APP_SIDE

    # ── 状态 ───────────────────────────────────────────────────────────────
    def _set_state(self, side: SideState, *, up: bool, reason: str) -> None:
        if side.up == up and side.reason == reason:
            return
        side.up = up
        side.reason = reason
        side.since = time.time()
        if up:
            LOG.info("%s 恢复服务（%s）", side.spec.name, reason)
        else:
            LOG.warning("%s 进入维护（%s）", side.spec.name, reason)

    async def probe_once(self) -> dict[str, str]:
        """探活两侧：计划维护直接判为不可用，其余按一次健康请求的结果定。"""
        result: dict[str, str] = {}
        for name, side in self.sides.items():
            if side.planned:
                self._set_state(side, up=False, reason="planned")
                result[name] = "planned"
                continue
            side.last_checked = time.time()
            try:
                response = await self.client.get(
                    side.spec.upstream + side.spec.probe_path,
                    timeout=self.config.probe_timeout,
                )
                ok = response.status_code < 500
                reason = "probe" if ok else f"probe {response.status_code}"
            except Exception as exc:  # 连接被拒、超时、协议错都算下线
                ok = False
                reason = f"probe failed: {type(exc).__name__}"
            self._set_state(side, up=ok, reason=reason)
            result[name] = "up" if ok else "down"
        return result

    async def probe_loop(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.probe_once()
            await asyncio.sleep(self.config.probe_interval)

    def status_payload(self) -> dict:
        sides = {
            name: {
                "up": side.up,
                "planned": side.planned,
                "reason": side.reason,
                "since": side.since,
                "upstream": side.spec.upstream,
                "probe": side.spec.probe_path,
            }
            for name, side in self.sides.items()
        }
        healthy = all(item["up"] for item in sides.values())
        return {
            "status": "ok" if healthy else "maintenance",
            "retry_after": self.config.retry_after,
            "sides": sides,
        }

    # ── 维护响应 ───────────────────────────────────────────────────────────
    @staticmethod
    def _wants_html(request: Request) -> bool:
        """判断这次请求是「用户打开页面」还是「程序取数据」。

        Sec-Fetch-Mode 是现代浏览器的权威信号；缺失时退回 Accept 判断。
        """
        mode = request.headers.get("sec-fetch-mode")
        if mode:
            return mode == "navigate"
        accept = request.headers.get("accept", "")
        return "text/html" in accept

    def _side_label(self) -> str:
        down = [name for name, side in self.sides.items() if not side.up]
        if not down:
            return "服务"
        if len(down) > 1:
            return "服务"
        return SIDE_LABELS.get(down[0], "服务")

    def maintenance_page(self, *, from_path: str) -> HTMLResponse:
        html = (
            self.page_template.replace("__SIDE_LABEL__", self._side_label())
            .replace("__FROM__", json.dumps(from_path))
            .replace("__RETRY_MS__", str(int(self.config.probe_interval * 1000)))
            .replace("__STATUS_URL__", "/__core/status")
        )
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store",
                "X-Robots-Tag": "noindex",
                "X-Core-Maintenance": "1",
            },
        )

    @staticmethod
    def _public_path(request: Request) -> str:
        path = request.url.path
        query = request.url.query
        return f"{path}?{query}" if query else path

    def unavailable(self, request: Request, side: SideState) -> Response:
        headers = {"Cache-Control": "no-store", "X-Core-Side": side.spec.name}
        if self._wants_html(request):
            from_path = self._public_path(request)
            location = "/under_maintenance"
            if from_path and from_path != "/":
                location += "?from=" + quote(from_path, safe="")
            return RedirectResponse(location, status_code=302, headers=headers)
        # 程序请求（fetch/XHR/静态资源）拿到的是能解析的应答，而不是跳转过去的 HTML。
        return JSONResponse(
            {
                "detail": f"{SIDE_LABELS.get(side.spec.name, '服务')}维护中，请稍后重试。",
                "status": "maintenance",
                "side": side.spec.name,
                "retry_after": self.config.retry_after,
            },
            status_code=503,
            headers={**headers, "Retry-After": str(self.config.retry_after)},
        )

    # ── 转发 ───────────────────────────────────────────────────────────────
    @staticmethod
    def _upstream_url(spec: SideSpec, request: Request) -> str:
        raw_path = request.scope.get("raw_path")
        path = raw_path.decode("latin-1") if raw_path else request.url.path
        target = spec.upstream + (path if path.startswith("/") else "/" + path)
        if request.url.query:
            target += "?" + request.url.query
        return target

    async def proxy(self, request: Request, side: SideState) -> Response:
        headers = [
            (key, value)
            for key, value in request.headers.raw
            if key.decode("latin-1").lower() not in HOP_BY_HOP
        ]
        # 真实客户端 IP 由隧道写在 CF-Connecting-IP 上，原样透传：功能页只信任回环来源的
        # 这些头，核心正好在回环上，限流与日志才看得到真实来源。
        body = request.stream() if request.method not in ("GET", "HEAD") else None
        upstream_request = self.client.build_request(
            request.method, self._upstream_url(side.spec, request), headers=headers, content=body
        )
        upstream = await self.client.send(upstream_request, stream=True)

        cookies = [
            value.decode("latin-1")
            for key, value in upstream.headers.raw
            if key.decode("latin-1").lower() == "set-cookie"
        ]
        response_headers = [
            (key.decode("latin-1"), value.decode("latin-1"))
            for key, value in upstream.headers.raw
            if key.decode("latin-1").lower() not in RESPONSE_DROP
            and key.decode("latin-1").lower() != "set-cookie"
        ]
        response = StreamingResponse(
            self._stream(upstream),
            status_code=upstream.status_code,
            headers=dict(response_headers),
        )
        # set-cookie 可能有多条，dict 会折叠，所以构造完再逐条追加。
        for cookie in cookies:
            response.raw_headers.append((b"set-cookie", cookie.encode("latin-1")))
        response.raw_headers.append((b"x-core-upstream", side.spec.name.encode("latin-1")))
        return response

    @staticmethod
    async def _stream(upstream: httpx.Response):
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    # ── 入口 ───────────────────────────────────────────────────────────────
    async def handle(self, request: Request) -> Response:
        path = request.url.path
        if path == "/under_maintenance":
            return self.maintenance_page(from_path=request.query_params.get("from", ""))
        if path == "/__core/status":
            return JSONResponse(self.status_payload(), headers={"Cache-Control": "no-store"})
        if path.startswith(CORE_PREFIXES):
            return JSONResponse({"detail": "not found"}, status_code=404)

        target = self.route_of(path)
        side = self.sides[target]
        if not side.up:
            return self.unavailable(request, side)
        try:
            return await self.proxy(request, side)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            # 连接不上：立刻判下线并给出维护页，而不是把 502 丢给用户。
            self._set_state(side, up=False, reason=f"proxy: {type(exc).__name__}")
            return self.unavailable(request, side)

    async def aclose(self) -> None:
        await self.client.aclose()


def create_app(
    config: Config | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    core: Core | None = None,
) -> Starlette:
    core = core or Core(config or Config(), transport=transport)

    async def endpoint(request: Request) -> Response:
        return await core.handle(request)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        await core.probe_once()
        task = asyncio.create_task(core.probe_loop())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await core.aclose()

    app = Starlette(
        routes=[
            Route(
                "/{path:path}",
                endpoint,
                methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
            )
        ],
        lifespan=lifespan,
    )
    app.state.core = core
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Lawver 分流核心")
    parser.add_argument("--config", default=os.environ.get("LAWVER_ROUTER_CONFIG"))
    parser.add_argument("--check", action="store_true", help="只探活一次并打印状态后退出")
    args = parser.parse_args()

    config = Config.from_file_and_env(args.config)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.check:
        core = Core(config)
        try:
            result = asyncio.run(core.probe_once())
        finally:
            asyncio.run(core.aclose())
        print(json.dumps({"probes": result, **core.status_payload()}, ensure_ascii=False, indent=2))
        return 0

    LOG.info(
        "分流核心监听 %s:%s → 功能页 %s、介绍页 %s（状态目录 %s）",
        config.host,
        config.port,
        config.app_upstream,
        config.intro_upstream,
        config.state_dir,
    )
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
