"""
模块描述：北大法宝 MCP 客户端与法条检索适配层的回归测试。

不发起真实网络请求：直接 mock `mcp.pkulaw_mcp.requests`，锁定
「URL/鉴权头是否按官方接入文档发对」以及「失败原因是否具体可操作」。
"""

import json
import os
import unittest
from unittest import mock

from mcp import pkulaw_client, pkulaw_mcp


# 选定数据源的用例一律显式设定这两个变量：某些用例（如 test_settings_routes）会在
# os.environ 里留下 PKU_ACCESS_TOKEN，靠"有没有令牌"判断模式会被测试顺序左右。
LOCAL_ENV = {"PKU_LAW_SOURCE": "", "PKU_ACCESS_TOKEN": ""}
TOKEN = "sk-pkulaw-test"
REMOTE_ENV = {"PKU_LAW_SOURCE": "remote", "PKU_ACCESS_TOKEN": TOKEN}


class _FakeResponse:
    """requests.Response 的最小替身，只覆盖客户端真正用到的成员。"""

    def __init__(
        self,
        status_code: int = 200,
        body: bytes | str = b"",
        *,
        headers: dict | None = None,
        encoding: str = "utf-8",
    ):
        self.status_code = status_code
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = dict(headers or {})
        self.encoding = encoding
        self.closed = False

    @property
    def text(self) -> str:
        return self._body.decode(self.encoding, errors="replace")

    def iter_content(self, chunk_size: int = 1):
        for start in range(0, len(self._body), max(1, chunk_size)):
            yield self._body[start : start + chunk_size]

    def close(self):
        self.closed = True


def _json_response(payload: dict, **kwargs) -> _FakeResponse:
    return _FakeResponse(body=json.dumps(payload), **kwargs)


def _sse_response(messages: list[dict], **kwargs) -> _FakeResponse:
    body = "".join("event: message\ndata: %s\n\n" % json.dumps(m) for m in messages)
    return _FakeResponse(body=body, headers={"Content-Type": "text/event-stream"}, **kwargs)


def _client(service: str = "law_search") -> pkulaw_mcp.PkulawMcpClient:
    with mock.patch.dict(os.environ, REMOTE_ENV):
        return pkulaw_mcp.PkulawMcpClient(service)


class EndpointResolutionTests(unittest.TestCase):
    def test_defaults_match_official_docs(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in ("PKU_LAW_SEARCH_ENDPOINT", "PKU_DOC_LINK_ENDPOINT"):
                os.environ.pop(name, None)
            self.assertEqual(
                pkulaw_mcp.resolve_endpoint("law_search"),
                "https://apim-gateway.pkulaw.com/mcp-law-search-service",
            )
            self.assertEqual(
                pkulaw_mcp.resolve_endpoint("doc_link"),
                "https://apim-gateway.pkulaw.com/add-doc-link",
            )

    def test_suffixed_services_keep_their_documented_url(self):
        """聚合网关与检察/执法文书的地址是带 /mcp 后缀的，不能按配置型 server 的写法改写。"""
        self.assertEqual(
            pkulaw_mcp.resolve_endpoint("law_agg"),
            "https://apim-gateway.pkulaw.com/mcp-law-agg/1.0.0/mcp",
        )
        self.assertEqual(
            pkulaw_mcp.resolve_endpoint("enforcement_doc"),
            "https://apim-gateway.pkulaw.com/pkulaw-enforcement-doc/mcp",
        )

    def test_env_override_is_honoured(self):
        with mock.patch.dict(
            os.environ,
            {"PKU_LAW_SEARCH_ENDPOINT": "https://apim-gateway.pkulaw.com/mcp-law"},
        ):
            self.assertEqual(
                pkulaw_mcp.resolve_endpoint("law_search"),
                "https://apim-gateway.pkulaw.com/mcp-law",
            )

    def test_non_official_endpoints_are_rejected(self):
        """凭据只允许发给官方网关，配置被改写时不至于把 Token 送出去。"""
        for bad in (
            "http://apim-gateway.pkulaw.com/mcp-law",
            "https://evil.example/mcp",
            "https://user:pw@apim-gateway.pkulaw.com/mcp-law",
            "https://apim-gateway.pkulaw.com/mcp-law?x=1",
        ):
            with mock.patch.dict(os.environ, {"PKU_LAW_SEARCH_ENDPOINT": bad}):
                with self.assertRaises(pkulaw_mcp.PkulawMcpError):
                    pkulaw_mcp.resolve_endpoint("law_search")

    def test_unknown_service_is_rejected(self):
        with self.assertRaises(pkulaw_mcp.PkulawMcpError):
            pkulaw_mcp.resolve_endpoint("nope")

    def test_missing_token_is_reported(self):
        with mock.patch.dict(os.environ, LOCAL_ENV):
            self.assertFalse(pkulaw_mcp.is_configured())
            with self.assertRaises(pkulaw_mcp.PkulawNotConfiguredError):
                pkulaw_mcp.PkulawMcpClient("law_search")

    def test_not_configured_error_is_also_an_mcp_error(self):
        """未配置属于可预期错误的一种：调用方一句 except PkulawMcpError 就能接住。"""
        self.assertTrue(issubclass(pkulaw_mcp.PkulawNotConfiguredError, pkulaw_mcp.PkulawMcpError))


class ResponseDecodingTests(unittest.TestCase):
    def test_plain_json_response(self):
        client = _client()
        response = _FakeResponse(headers={"Content-Type": "application/json"})
        self.assertEqual(
            client._decode_response(response, b'{"result": {"ok": 1}}'),
            {"result": {"ok": 1}},
        )

    def test_sse_response(self):
        client = _client()
        response = _FakeResponse(headers={"Content-Type": "text/event-stream"})
        raw = b'event: message\ndata: {"jsonrpc": "2.0", "id": 1, "result": {"ok": 2}}\n\n'
        # 解出的是整条 JSON-RPC 消息，result 由 call_tool 再取一层
        self.assertEqual(
            client._decode_response(response, raw),
            {"jsonrpc": "2.0", "id": 1, "result": {"ok": 2}},
        )

    def test_sse_error_frame_wins_over_result(self):
        client = _client()
        response = _FakeResponse(headers={"Content-Type": "text/event-stream"})
        raw = (
            b'data: {"result": {"ok": 1}}\n\n'
            b'data: {"error": {"code": -32602, "message": "bad params"}}\n\n'
        )
        self.assertIn("error", client._decode_response(response, raw))

    def test_empty_body_is_an_error(self):
        client = _client()
        response = _FakeResponse(headers={"Content-Type": "application/json"})
        with self.assertRaises(pkulaw_mcp.PkulawMcpError):
            client._decode_response(response, b"   ")

    def test_unparseable_body_is_an_error(self):
        client = _client()
        response = _FakeResponse(headers={"Content-Type": "application/json"})
        with self.assertRaises(pkulaw_mcp.PkulawMcpError):
            client._decode_response(response, b"<html>oops</html>")


class PayloadExtractionTests(unittest.TestCase):
    def test_structured_content_envelope(self):
        result = {
            "structuredContent": {"Message": "成功", "Data": [{"Title": "刑法修正案(三)"}]},
            "content": [{"type": "text", "text": "ignored"}],
        }
        self.assertEqual(
            pkulaw_mcp._extract_tool_payload(result),
            {"Message": "成功", "Data": [{"Title": "刑法修正案(三)"}]},
        )

    def test_single_text_part_is_json_decoded(self):
        result = {"content": [{"type": "text", "text": '[{"article": "原文"}]'}]}
        self.assertEqual(pkulaw_mcp._extract_tool_payload(result), [{"article": "原文"}])

    def test_plain_text_part_stays_text(self):
        result = {"content": [{"type": "text", "text": "未找到相关法条"}]}
        self.assertEqual(pkulaw_mcp._extract_tool_payload(result), "未找到相关法条")

    def test_multiple_text_parts_are_collected(self):
        result = {
            "content": [
                {"type": "text", "text": "第一段"},
                {"type": "text", "text": "第二段"},
            ]
        }
        self.assertEqual(pkulaw_mcp._extract_tool_payload(result), "第一段\n第二段")

    def test_is_error_result_raises_with_server_text(self):
        result = {"isError": True, "content": [{"type": "text", "text": "积分不足"}]}
        with self.assertRaises(pkulaw_mcp.PkulawMcpError) as ctx:
            pkulaw_mcp._extract_tool_payload(result)
        self.assertIn("积分不足", str(ctx.exception))


class CallToolTests(unittest.TestCase):
    def _init_then_tool(self, tool_messages: list[_FakeResponse]):
        """按 客户端实际发出的顺序返回响应：initialize → initialized → tools/call。"""
        responses = [
            _json_response(
                {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "x"}},
                headers={"Mcp-Session-Id": "sess-7"},
            ),
            _FakeResponse(status_code=202),
            *tool_messages,
        ]
        return mock.patch.object(pkulaw_mcp.requests, "post", side_effect=responses)

    def test_handshake_headers_and_call_shape(self):
        tool_body = json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"content": [
            {"type": "text", "text": '[{"title": "中华人民共和国劳动合同法(2012修正)"}]'}
        ]}})
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("law_search")
            with self._init_then_tool([_FakeResponse(body=tool_body)]) as post_mock:
                payload = client.call_tool("search_article", {"text": "工伤", "size": 5})

        self.assertEqual(payload, [{"title": "中华人民共和国劳动合同法(2012修正)"}])

        calls = post_mock.call_args_list
        self.assertEqual(len(calls), 3)

        init_call = calls[0]
        self.assertEqual(init_call.args[0], client.endpoint)
        self.assertEqual(init_call.kwargs["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(init_call.kwargs["headers"]["Accept"], "application/json, text/event-stream")
        self.assertEqual(init_call.kwargs["json"]["method"], "initialize")
        self.assertFalse(init_call.kwargs["allow_redirects"])
        # URL 末尾不加 /mcp —— 直接打服务地址
        self.assertNotIn("/mcp", init_call.args[0].removeprefix("https://apim-gateway.pkulaw.com/"))

        self.assertEqual(calls[1].kwargs["json"]["method"], "notifications/initialized")

        tool_call = calls[2]
        self.assertEqual(tool_call.kwargs["json"]["method"], "tools/call")
        self.assertEqual(
            tool_call.kwargs["json"]["params"],
            {"name": "search_article", "arguments": {"text": "工伤", "size": 5}},
        )
        # 网关下发的会话 id 要带在后续请求上
        self.assertEqual(tool_call.kwargs["headers"]["Mcp-Session-Id"], "sess-7")

    def test_session_is_initialized_only_once(self):
        tool_body = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": []}})
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("law_search")
            with mock.patch.object(
                pkulaw_mcp.requests,
                "post",
                side_effect=[
                    _json_response({"jsonrpc": "2.0", "id": 1, "result": {}}),
                    _FakeResponse(status_code=202),
                    _FakeResponse(body=tool_body),
                    _FakeResponse(body=tool_body),
                ],
            ) as post_mock:
                client.call_tool("get_article", {"title": "民法典", "number": "第五百七十七条"})
                client.call_tool("get_article", {"title": "民法典", "number": "第五百七十七条"})

        methods = [call.kwargs["json"]["method"] for call in post_mock.call_args_list]
        self.assertEqual(methods.count("initialize"), 1)
        self.assertEqual(methods.count("tools/call"), 2)

    def test_http_401_is_actionable(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("law_search")
            with mock.patch.object(
                pkulaw_mcp.requests,
                "post",
                return_value=_FakeResponse(
                    status_code=401,
                    body="{}",
                    headers={"www-authenticate": 'Bearer error="invalid_token", error_description="The provided token is invalid"'},
                ),
            ) as post_mock:
                with self.assertRaises(pkulaw_mcp.PkulawMcpError) as ctx:
                    client.call_tool("search_article", {"text": "工伤"})

        message = str(ctx.exception)
        self.assertIn("401", message)
        self.assertIn("访问令牌无效或缺失", message)
        self.assertIn("invalid_token", message)
        # 鉴权都失败了，不该继续发 initialized / tools/call
        self.assertEqual(post_mock.call_count, 1)

    def test_jsonrpc_error_is_surfaced(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("law_search")
            with mock.patch.object(
                pkulaw_mcp.requests,
                "post",
                return_value=_json_response(
                    {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
                ),
            ):
                with self.assertRaises(pkulaw_mcp.PkulawMcpError) as ctx:
                    client.call_tool("search_article", {"text": "工伤"})

        message = str(ctx.exception)
        self.assertIn("Method not found", message)
        self.assertIn("-32601", message)

    def test_tool_outside_the_service_is_rejected(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("doc_link")
            with mock.patch.object(pkulaw_mcp.requests, "post") as post_mock:
                with self.assertRaises(pkulaw_mcp.PkulawMcpError):
                    client.call_tool("search_article", {"text": "工伤"})
        post_mock.assert_not_called()

    def test_undeclared_tool_names_are_allowed_for_agg_service(self):
        """聚合网关文档要求先读 tools/list 再按用途匹配，不应被本地白名单挡住。"""
        body = json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"ok": True}}})
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("law_agg")
            with mock.patch.object(
                pkulaw_mcp.requests,
                "post",
                side_effect=[
                    _json_response({"jsonrpc": "2.0", "id": 1, "result": {}}),
                    _FakeResponse(status_code=202),
                    _FakeResponse(body=body),
                ],
            ):
                self.assertEqual(client.call_tool("mcp-law-search-service_search_article", {}), {"ok": True})

    def test_oversized_response_is_aborted(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("law_search")
            with mock.patch.object(pkulaw_mcp, "_MAX_RESPONSE_BYTES", 64):
                with mock.patch.object(
                    pkulaw_mcp.requests,
                    "post",
                    return_value=_FakeResponse(
                        body=b"x" * 4096, headers={"Content-Type": "application/json"}
                    ),
                ):
                    with self.assertRaises(pkulaw_mcp.PkulawMcpError) as ctx:
                        client.call_tool("search_article", {"text": "工伤"})
        self.assertIn("过大", str(ctx.exception))

    def test_transport_failure_is_wrapped(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            client = pkulaw_mcp.PkulawMcpClient("law_search")
            with mock.patch.object(
                pkulaw_mcp.requests,
                "post",
                side_effect=pkulaw_mcp.requests.exceptions.ConnectTimeout("timed out"),
            ):
                with self.assertRaises(pkulaw_mcp.PkulawMcpError) as ctx:
                    client.call_tool("search_article", {"text": "工伤"})
        self.assertIn("网络请求失败", str(ctx.exception))


class SearchArticleMappingTests(unittest.TestCase):
    """search_article 的返回归一化：法宝数组 → 既有 {success, result} 文本形态。"""

    ITEMS = [
        {
            "gid": "7ab5e7d605f859e6bdfb",
            "title": "中华人民共和国劳动合同法(2012修正)",
            "article": "第八十七条　用人单位违反本法规定解除或者终止劳动合同的……",
            "timeliness": "现行有效",
            "effectiveness": "法律",
            "url": "https://pkulaw.com/chl/7ab5e7d605f859e6bdfb.html",
        }
    ]

    def test_remote_result_carries_source_and_timeliness(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(
                pkulaw_client, "_remote_client"
            ) as client_mock:
                client_mock.return_value.call_tool.return_value = self.ITEMS
                payload = json.loads(pkulaw_client.search_article("违法解除劳动合同"))

        self.assertTrue(payload["success"])
        result = payload["result"]
        self.assertIn("《中华人民共和国劳动合同法(2012修正)》", result)
        self.assertIn("第八十七条", result)
        # 官方文档要求引用时带时效性与原文链接，这两个必须出现在结果里
        self.assertIn("时效性: 现行有效", result)
        self.assertIn("来源: https://pkulaw.com/chl/7ab5e7d605f859e6bdfb.html", result)
        client_mock.return_value.call_tool.assert_called_once_with(
            "search_article", {"text": "违法解除劳动合同", "size": 5}
        )

    def test_empty_remote_result_is_a_structured_error(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                client_mock.return_value.call_tool.return_value = []
                payload = json.loads(pkulaw_client.search_article("无关描述"))
        self.assertFalse(payload["success"])
        self.assertIn("未检索到", payload["message"])

    def test_remote_failure_is_not_silently_downgraded_to_local(self):
        """法宝模式下失败必须报出原因，不能悄悄改用本地语料回答。"""
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                client_mock.return_value.call_tool.side_effect = pkulaw_mcp.PkulawMcpError(
                    "法宝服务返回 403：访问令牌权限不足（可能未订阅该服务或积分不足）"
                )
                with mock.patch.object(pkulaw_client, "_local_search_engine") as local_mock:
                    payload = json.loads(pkulaw_client.search_article("工伤"))
        self.assertFalse(payload["success"])
        self.assertIn("403", payload["message"])
        local_mock.assert_not_called()


class GetArticleMappingTests(unittest.TestCase):
    REMOTE_ITEM = {
        "gid": "aa00daaeb5a4fe4ebdfb",
        "title": "中华人民共和国民法典",
        "article": "第五百七十七条　当事人一方不履行合同义务或者履行合同义务不符合约定的……",
        "timeliness": "现行有效",
        "url": "https://pkulaw.com/chl/aa00daaeb5a4fe4ebdfb.html",
    }

    def test_remote_get_article_keeps_existing_shape(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                client_mock.return_value.call_tool.return_value = self.REMOTE_ITEM
                payload = json.loads(pkulaw_client.get_article("民法典", "第五百七十七条"))

        self.assertTrue(payload["success"])
        self.assertEqual(payload["title"], "中华人民共和国民法典")
        self.assertIn("第五百七十七条", payload["content"])
        self.assertEqual(payload["url"], self.REMOTE_ITEM["url"])
        self.assertEqual(payload["timeliness"], "现行有效")
        client_mock.return_value.call_tool.assert_called_once_with(
            "get_article", {"title": "民法典", "number": "第五百七十七条"}
        )

    def test_missing_number_is_rejected_before_any_call(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                payload = json.loads(pkulaw_client.get_article("民法典", ""))
        self.assertFalse(payload["success"])
        client_mock.assert_not_called()


class LinkedContentMappingTests(unittest.TestCase):
    def test_markdown_blocks_are_joined(self):
        payload_in = [
            {"type": "text", "text": "根据《[中华人民共和国长江保护法](https://www.pkulaw.com/chl/x.html)》…"}
        ]
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                client_mock.return_value.call_tool.return_value = payload_in
                payload = json.loads(pkulaw_client.get_linked_content("根据《长江保护法》第九十三条"))

        self.assertTrue(payload["success"])
        self.assertIn("[中华人民共和国长江保护法]", payload["text"])
        client_mock.return_value.call_tool.assert_called_once_with(
            "get_linked_content", {"message": "根据《长江保护法》第九十三条"}
        )

    def test_empty_payload_is_a_structured_error(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                client_mock.return_value.call_tool.return_value = []
                payload = json.loads(pkulaw_client.get_linked_content("无引用文本"))
        self.assertFalse(payload["success"])


class ModeSelectionTests(unittest.TestCase):
    def _stub_local_search(self):
        patcher = mock.patch.object(pkulaw_client, "_local_search_engine")
        patched = patcher.start()
        self.addCleanup(patcher.stop)
        patched.return_value.law_fuzzy_search.return_value = json.dumps(
            {
                "success": True,
                "data": [
                    {
                        "law_name": "测试法",
                        "article_number": "第一条",
                        "content": "正文",
                        "url": "u",
                    }
                ],
            }
        )
        return patched

    def test_default_source_is_local(self):
        with mock.patch.dict(os.environ, LOCAL_ENV):
            self.assertEqual(pkulaw_mcp.source(), "local")
            self.assertFalse(pkulaw_mcp.is_configured())

    def test_stale_token_alone_does_not_switch_to_remote(self):
        """历史 .env 里残留旧令牌时，产品必须仍用本地库作答 —— 这是最要紧的一条护栏。"""
        self._stub_local_search()
        with mock.patch.dict(
            os.environ, {"PKU_LAW_SOURCE": "", "PKU_ACCESS_TOKEN": "legacy-token-from-old-env"}
        ):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                payload = json.loads(pkulaw_client.search_article("测试"))
        self.assertTrue(payload["success"])
        self.assertIn("《测试法》第一条", payload["result"])
        client_mock.assert_not_called()

    def test_explicit_remote_switch_enables_pkulaw(self):
        for value in ("remote", "REMOTE", "pkulaw", "1", "true"):
            with mock.patch.dict(
                os.environ, {"PKU_LAW_SOURCE": value, "PKU_ACCESS_TOKEN": TOKEN}
            ):
                self.assertEqual(pkulaw_mcp.source(), "remote", value)
                self.assertTrue(pkulaw_mcp.is_configured())

    def test_declared_remote_without_token_reports_instead_of_using_local(self):
        """声明了远程却没给令牌：要报出原因，不能悄悄回落到本地库作答。"""
        self._stub_local_search()
        with mock.patch.dict(os.environ, {"PKU_LAW_SOURCE": "remote", "PKU_ACCESS_TOKEN": ""}):
            self.assertTrue(pkulaw_client._remote_enabled())
            payload = json.loads(pkulaw_client.get_article("民法典", "第五百七十七条"))
        self.assertFalse(payload["success"])
        self.assertIn("未配置访问令牌", payload["message"])

    def test_without_remote_switch_everything_stays_local(self):
        self._stub_local_search()
        with mock.patch.dict(os.environ, LOCAL_ENV):
            with mock.patch.object(pkulaw_client, "_remote_client") as client_mock:
                payload = json.loads(pkulaw_client.search_article("测试"))
        self.assertTrue(payload["success"])
        self.assertIn("《测试法》第一条", payload["result"])
        client_mock.assert_not_called()

    def test_ensure_law_database_ready_skips_local_build_in_remote_mode(self):
        with mock.patch.dict(os.environ, REMOTE_ENV):
            with mock.patch.object(pkulaw_client, "_local_search_engine") as local_mock:
                status = pkulaw_client.ensure_law_database_ready()
        self.assertEqual(status["mode"], "remote")
        local_mock.assert_not_called()

    def test_ensure_law_database_ready_uses_local_build_by_default(self):
        with mock.patch.dict(os.environ, LOCAL_ENV):
            with mock.patch.object(pkulaw_client, "_local_search_engine") as local_mock:
                local_mock.return_value.ensure_law_database_ready.return_value = {"mode": "unchanged"}
                status = pkulaw_client.ensure_law_database_ready()
        self.assertEqual(status, {"mode": "unchanged"})
        local_mock.return_value.ensure_law_database_ready.assert_called_once_with(force_rebuild=False)


class MappingListTests(unittest.TestCase):
    def test_structured_data_envelopes_are_unwrapped(self):
        self.assertEqual(
            pkulaw_client._as_mapping_list({"Message": "成功", "Data": [{"Title": "x"}]}),
            [{"Title": "x"}],
        )
        self.assertEqual(pkulaw_client._as_mapping_list({"data": [{"a": 1}]}), [{"a": 1}])
        self.assertEqual(pkulaw_client._as_mapping_list([{"a": 1}]), [{"a": 1}])
        self.assertEqual(pkulaw_client._as_mapping_list([]), [])
        self.assertEqual(pkulaw_client._as_mapping_list("文本"), [])
        self.assertEqual(pkulaw_client._first_mapping({"title": "单对象"}), {"title": "单对象"})


if __name__ == "__main__":
    unittest.main()
