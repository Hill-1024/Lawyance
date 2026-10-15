"""
模块描述：北大法宝开放平台 MCP 客户端（streamableHttp + Bearer），按官方接入文档实现。

接入指南：https://mcp.pkulaw.com/docs?doc=mcp-integration

照文档抄的三条硬约束（文档原话是「能省 80% 的问题」）：
  1. URL 就用文档「服务信息」里的地址，**不要自行增删 /mcp 后缀**（配置型 server
     不带后缀，聚合网关与检察/执法文书带）；
  2. 认证头是 `Authorization: Bearer <Token>` —— Bearer 与 Token 之间有且只有一个空格；
  3. 传输是 MCP streamable HTTP：对服务 URL 直接 POST JSON-RPC 2.0，`Accept` 同时
     声明 application/json 与 text/event-stream —— 响应既可能是裸 JSON，也可能是 SSE。

这一层只负责传输与解包，不臆测业务字段：各服务的返回结构差异很大（语义检索返回数组、
关键词检索返回 structuredContent.Data、超链返回 [{type, text}]），统一由
`_extract_tool_payload` 容错解出，再由 `pkulaw_client` 归一化成既有返回形态。
"""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlparse

import requests


logger = logging.getLogger(__name__)

# 响应体读取上限：法宝是受信上游，但仍按其余外部客户端同一标准限长，防止异常响应耗尽内存。
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# SSE 响应里一帧就是一条 JSON-RPC 消息，正常只有一两帧；超出即视为异常流。
_MAX_SSE_EVENTS = 64

_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 30

_PROTOCOL_VERSION = "2025-06-18"
_ACCEPT_HEADER = "application/json, text/event-stream"

# 网关主机白名单：凭据只允许发给官方网关，避免配置被改写后把 Token 送到任意主机。
_ALLOWED_HOST = "apim-gateway.pkulaw.com"

# 出错时 HTTP 状态码 → 人话。法宝走 WSO2 网关，凭据问题几乎都落在 401/403。
_HTTP_HINTS = {
    400: "请求被拒绝（参数或工具名不对）",
    401: "访问令牌无效或缺失",
    403: "访问令牌权限不足（可能未订阅该服务或积分不足）",
    404: "服务地址不存在（端点可能已变更）",
    429: "调用过于频繁，请降低频率",
    500: "法宝服务端错误",
    502: "法宝服务暂时不可用",
    503: "法宝服务暂时不可用",
}


# 官方文档给出的服务清单。`endpoint` 一律照抄各服务「服务信息」里的地址——
# 注意后缀并不统一：接入指南的 9 个配置型 server 不带 `/mcp`，而聚合网关与
# 检察/执法文书三个是带 `/mcp`（或 `/1.0.0/mcp`）的，不能自行增删。
# `tools` 取自各服务文档「三、提供的工具」；工具名未核准的留空 —— 不猜名字，
# 调用时按文档要求先读 tools/list。
PKULAW_SERVICES: dict[str, dict[str, object]] = {
    "law_search": {
        "label": "检索法律法规-语义",
        "endpoint": "https://apim-gateway.pkulaw.com/mcp-law-search-service",
        "tools": ("search_article", "get_article"),
    },
    "law_keyword": {
        "label": "检索法律法规-关键词",
        "endpoint": "https://apim-gateway.pkulaw.com/mcp-law",
        "tools": ("get_law_list",),
    },
    "law_item": {
        "label": "精准查找法条-关键词",
        "endpoint": "https://apim-gateway.pkulaw.com/mcp-fatiao",
        "tools": ("get_law_item_content",),
    },
    "doc_link": {
        "label": "法宝超链",
        "endpoint": "https://apim-gateway.pkulaw.com/add-doc-link",
        "tools": ("get_linked_content",),
    },
    "law_recognition": {
        "label": "法条识别与溯源",
        "endpoint": "https://apim-gateway.pkulaw.com/law_recognition",
        "tools": ("law_recognition",),
    },
    "case_number_recognition": {
        "label": "案号识别与溯源",
        "endpoint": "https://apim-gateway.pkulaw.com/case_number_recognition",
        "tools": ("anhao_recognition",),
    },
    "citation_validator": {
        "label": "修正生成幻觉-法条",
        "endpoint": "https://apim-gateway.pkulaw.com/pku_citation_validator",
        # 入参是 userlaw / answerlaw / prompt 三个平铺顶层字段，不要再套一层 param。
        "tools": ("adjust_provisions",),
    },
    "case_keyword": {
        "label": "检索司法案例-关键词",
        "endpoint": "https://apim-gateway.pkulaw.com/mcp-case",
        "tools": ("get_case_list",),
    },
    "case_semantic": {
        "label": "检索司法案例-语义",
        "endpoint": "https://apim-gateway.pkulaw.com/mcp-case-search-service",
        "tools": ("search_case",),
    },
    "statute_history": {
        "label": "法规与法条沿革",
        "endpoint": "https://apim-gateway.pkulaw.com/pkulaw-statute-history",
        "tools": (
            "list_law_versions",
            "list_related_statutes",
            "get_article_history",
            "diff_article_versions",
        ),
    },
    "law_agg": {
        "label": "法律智能检索",
        "endpoint": "https://apim-gateway.pkulaw.com/mcp-law-agg/1.0.0/mcp",
        # 文档明确：聚合套件 18 个工具，名字可能带服务前缀，且返回形态不统一，
        # 必须先读 tools/list 按用途匹配。故不在此声明工具名。
        "tools": (),
    },
    "procuratorate_doc": {
        "label": "检索检察文书",
        "endpoint": "https://apim-gateway.pkulaw.com/pkulaw-procuratorate-doc/mcp",
        "tools": ("search_procuratorate",),
    },
    "enforcement_doc": {
        "label": "检索行政执法",
        "endpoint": "https://apim-gateway.pkulaw.com/pkulaw-enforcement-doc/mcp",
        "tools": ("search_enforcement",),
    },
}

# 各服务端点的可覆盖环境变量名，按服务 key 声明。
ENDPOINT_ENV: dict[str, str] = {
    "law_search": "PKU_LAW_SEARCH_ENDPOINT",
    "doc_link": "PKU_DOC_LINK_ENDPOINT",
}


class PkulawMcpError(RuntimeError):
    """调用法宝过程中的可预期错误（未配置、凭据、地址、业务错、网络）。"""


class PkulawNotConfiguredError(PkulawMcpError):
    """声明了法宝模式但 PKU_ACCESS_TOKEN 为空。

    继承 PkulawMcpError，调用方用一句 `except PkulawMcpError` 就能同时接住
    "没配" 和 "配了但出错"，不必分别处理。
    """


def access_token() -> str:
    """调用期读取令牌：既不因缺配置阻断后端启动，也让环境热更新即时生效。"""
    return (os.getenv("PKU_ACCESS_TOKEN") or "").strip()


# 数据源开关。默认本地法库 —— 只凭"存在 PKU_ACCESS_TOKEN"不足以切远程：
# 历史 .env 里可能残留早已停用的旧令牌，那样会在无人察觉的情况下把产品从
# 本地检索切到一个连不通（令牌失效/积分不足）的数据源上。故改成显式声明。
_SOURCE_ENV = "PKU_LAW_SOURCE"
_REMOTE_SOURCE_VALUES = {"remote", "pkulaw", "1", "true", "yes", "on"}


def source() -> str:
    """当前法条检索数据源：`remote`（北大法宝 MCP）或 `local`（本地法库，默认）。

    只有显式声明才切远程；声明了却没给令牌同样按远程处理，让第一个法条查询
    直接报出"未配置访问令牌"，而不是悄悄用本地库回答。
    """
    raw = (os.getenv(_SOURCE_ENV) or "").strip().lower()
    return "remote" if raw in _REMOTE_SOURCE_VALUES else "local"


def is_configured() -> bool:
    """是否处于法宝模式（按显式声明判断，不看令牌是否存在）。"""
    return source() == "remote"


def resolve_endpoint(service: str) -> str:
    """按「环境变量覆盖 → 文档默认值」解析端点，并校验到官方 https 网关。"""
    spec = PKULAW_SERVICES.get(service)
    if spec is None:
        raise PkulawMcpError("未知的法宝服务: %s" % service)

    env_name = ENDPOINT_ENV.get(service)
    override = (os.getenv(env_name) or "").strip() if env_name else ""
    endpoint = override or str(spec["endpoint"])

    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname != _ALLOWED_HOST
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise PkulawMcpError(
            "法宝服务地址配置非法（当前为 %s）。正确地址应为：%s"
            % (endpoint, spec["endpoint"])
        )
    return endpoint


def _describe_http_error(status: int, response) -> str:
    """HTTP 错误连同响应正文一起说清楚 —— 网关会在 www-authenticate 里写明原因。"""
    hint = _HTTP_HINTS.get(status, "未知错误")
    detail = ""
    try:
        authenticate = (response.headers.get("www-authenticate") or "").strip()
        body = (response.text or "").strip()
        raw = authenticate or body
        if raw:
            detail = raw.replace("\n", " ")[:200]
    except Exception:
        pass
    msg = "法宝服务返回 %d：%s" % (status, hint)
    if detail:
        msg += "。服务端说明：%s" % detail
    return msg


def _maybe_json(text: str):
    """文本长得像 JSON 就解析，否则原样返回 —— 各服务返回形态不一致，只能容错。"""
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return text
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return text


def _content_text(result: dict) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        str(part.get("text") or "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part.strip())


def _extract_tool_payload(result: object):
    """把 MCP tools/call 的 result 解成业务载荷。

    兼容三种已知形态：
      · structuredContent（关键词检索服务用它承载 Data 列表）
      · content=[{type:"text", text:"<JSON>"}]（语义检索、超链服务）
      · 直接就是业务体（某些网关会透传）
    """
    if not isinstance(result, dict):
        return result

    if result.get("isError"):
        raise PkulawMcpError(_content_text(result) or "法宝服务返回错误")

    structured = result.get("structuredContent")
    if isinstance(structured, (dict, list)) and structured:
        return structured

    content = result.get("content")
    if isinstance(content, list):
        texts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        texts = [text for text in texts if text.strip()]
        if len(texts) == 1:
            return _maybe_json(texts[0])
        if texts:
            parsed = [_maybe_json(text) for text in texts]
            if all(isinstance(item, (dict, list)) for item in parsed):
                return parsed
            return "\n".join(texts)

    return result


class PkulawMcpClient:
    """单个法宝 MCP 服务的 streamable HTTP 客户端。

    每次调用都按文档做标准握手：initialize → notifications/initialized → tools/call。
    会话 id 由网关在响应头 `Mcp-Session-Id` 下发；没有会话的网关（无状态）也能正常工作。
    """

    def __init__(self, service: str, *, token: str | None = None):
        self.service = service
        self.endpoint = resolve_endpoint(service)
        resolved = token if token is not None else access_token()
        if not resolved:
            raise PkulawNotConfiguredError("北大法宝尚未配置访问令牌（PKU_ACCESS_TOKEN）")
        self.token = resolved
        self.headers = {
            "Authorization": "Bearer %s" % self.token,
            "Content-Type": "application/json",
            "Accept": _ACCEPT_HEADER,
        }
        self._session_id = ""
        self._session_ready = False
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @staticmethod
    def _read_bounded(response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                raise PkulawMcpError("法宝服务响应过大")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _parse_sse(text: str) -> list[dict]:
        """解析 SSE 帧：一帧一条 JSON-RPC 消息，取其中的对象帧。"""
        messages: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                messages.append(decoded)
            if len(messages) >= _MAX_SSE_EVENTS:
                break
        return messages

    def _decode_response(self, response, raw: bytes) -> dict:
        text = raw.decode(response.encoding or "utf-8", errors="replace").strip()
        if not text:
            raise PkulawMcpError("法宝服务返回空响应")

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in content_type or text.startswith(("event:", "data:")):
            messages = self._parse_sse(text)
            if not messages:
                raise PkulawMcpError("法宝服务返回的 SSE 响应里没有可解析的消息")
            for message in messages:
                if "error" in message:
                    return message
            for message in messages:
                if "result" in message:
                    return message
            return messages[-1]

        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PkulawMcpError("法宝服务响应解析失败：%s" % exc) from exc
        if not isinstance(decoded, dict):
            raise PkulawMcpError("法宝服务响应格式异常")
        return decoded

    def _post(self, payload: dict, *, notify: bool = False) -> tuple[dict, str]:
        headers = dict(self.headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS),
                allow_redirects=False,
                stream=True,
            )
        except requests.exceptions.RequestException as exc:
            raise PkulawMcpError("法宝服务网络请求失败：%s" % exc) from exc

        try:
            if response.status_code != 200:
                raise PkulawMcpError(_describe_http_error(response.status_code, response))
            session_id = (response.headers.get("Mcp-Session-Id") or "").strip()
            if notify:
                return {}, session_id
            raw = self._read_bounded(response)
            return self._decode_response(response, raw), session_id
        finally:
            response.close()

    def _raise_for_error(self, message: dict) -> None:
        error = message.get("error")
        if not isinstance(error, dict):
            raise PkulawMcpError("法宝服务返回错误：%s" % error)
        code = error.get("code")
        reason = error.get("message") or "未知原因"
        hint = _HTTP_HINTS.get(code) if isinstance(code, int) else None
        text = "法宝服务拒绝请求：%s" % reason
        if hint:
            text += "（%s）" % hint
        elif code not in (None, 0):
            text += "（错误码 %s）" % code
        raise PkulawMcpError(text)

    def _ensure_session(self) -> None:
        if self._session_ready:
            return
        message, session_id = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "lawver", "version": "1.0.0"},
                },
            }
        )
        if "error" in message:
            self._raise_for_error(message)
        self._session_id = session_id or self._session_id

        # 标准要求的 initialized 通知。无状态网关不需要它，失败也不该阻断调用。
        try:
            self._post(
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                notify=True,
            )
        except PkulawMcpError as exc:
            logger.debug("法宝 initialized 通知未送达（按无状态网关继续）: %s", exc)

        self._session_ready = True

    def call_tool(self, name: str, arguments: dict):
        """调用服务上的一个工具，返回解包后的业务载荷。"""
        spec = PKULAW_SERVICES.get(self.service) or {}
        declared = tuple(spec.get("tools") or ())
        if declared and name not in declared:
            raise PkulawMcpError(
                "工具 %s 不属于法宝服务「%s」" % (name, spec.get("label") or self.service)
            )

        self._ensure_session()
        message, session_id = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        self._session_id = session_id or self._session_id
        if "error" in message:
            self._raise_for_error(message)
        if "result" not in message:
            raise PkulawMcpError("法宝服务未返回工具结果")
        return _extract_tool_payload(message["result"])
