"""
模块描述：图片输入链路测试，锁定「图片作为工作区文件、由 image_reader 工具按需读取」。

架构约定：平台不再把图片自动附加到用户消息；模型通过 image_reader 工具读取，
工具结果里的图片载荷由 agent 循环转成随后一条 user 消息的 image_url
（OpenAI 规范要求 tool 消息 content 为字符串，实测数组形式会被端点 400 拒绝）。
"""

import asyncio
import base64
import importlib
import os
import sys
import tempfile
import unittest


TEST_SECRET = "y" * 32

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def purge_runtime_modules():
    """清掉所有直接 import 了 function_calling / tools 的模块，避免陈旧引用。"""
    prefixes = ("routes.", "services.", "agents.", "tools.", "infra.")
    roots = {
        "agent", "app_factory", "auth", "routes", "services",
        "agents", "tools", "mcps", "function_calling", "prompt_loader",
    }
    for name in list(sys.modules):
        if name in roots or name.startswith(prefixes):
            sys.modules.pop(name, None)


class _FakeCompletions:
    """按轮次返回预设响应，并记录每轮实际发出的 messages。"""

    def __init__(self, responder):
        self._responder = responder
        self.calls: list[list] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs.get("messages") or [])
        return self._responder(len(self.calls))


def _install_fake_client(test_case, function_calling_module, completions):
    original = function_calling_module.client
    function_calling_module.client = type(
        "FakeClient", (), {"chat": type("C", (), {"completions": completions})()}
    )()
    test_case.addCleanup(lambda: setattr(function_calling_module, "client", original))


def _collect_image_parts(messages: list) -> list[dict]:
    return [
        part
        for message in messages
        if isinstance(message, dict) and isinstance(message.get("content"), list)
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "image_url"
    ]


def _make_message_class():
    class _Msg:
        def __init__(self, content, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls
            self.reasoning_content = None
            self.thought_signature = None

    return _Msg


def _make_response_class():
    class _Resp:
        def __init__(self, message):
            self.choices = [type("Ch", (), {"message": message})()]
            self.usage = None

    return _Resp


class MultimodalInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp.name
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        purge_runtime_modules()
        self.workspace_service = importlib.import_module("services.workspace_service")
        self.multimodal = importlib.import_module("services.multimodal")
        self.function_calling = importlib.import_module("function_calling")

    def tearDown(self):
        self.tmp.cleanup()
        purge_runtime_modules()

    def _write_workspace_image(self, scope_user: str, scope_conv: str, name: str, payload: bytes) -> str:
        directory = os.path.join("TEMP", scope_user, scope_conv)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(payload)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path.replace("\\", "/")

    def _tool_handler(self):
        tools_module = importlib.import_module("tools")
        return tools_module.registry._by_name["image_reader"].handler

    # ── 上传校验 ──

    def test_image_extensions_are_accepted(self):
        for name in ("a.png", "b.jpg", "c.jpeg", "d.webp", "e.gif", "f.bmp"):
            self.assertEqual(self.workspace_service.validate_workspace_filename(name), name)

    def test_non_image_extensions_still_rejected(self):
        with self.assertRaises(Exception):
            self.workspace_service.validate_workspace_filename("payload.exe")

    def test_magic_bytes_detection(self):
        sniff = self.workspace_service.sniff_image_mime
        self.assertEqual(sniff(PNG_BYTES), "image/png")
        self.assertEqual(sniff(JPEG_BYTES), "image/jpeg")
        self.assertIsNone(sniff(b"MZ\x90\x00 not an image"))

    def test_extension_content_mismatch_rejected(self):
        with self.assertRaises(Exception):
            self.workspace_service.validate_image_content("fake.gif", PNG_BYTES)
        with self.assertRaises(Exception):
            self.workspace_service.validate_image_content("fake.png", b"MZ\x90\x00")

    # ── 路径形态 ──

    def test_absolute_workspace_path_is_normalized(self):
        abs_path = os.path.abspath(os.path.join("TEMP", "u1", "c1", "pic.png"))
        self.assertEqual(self.workspace_service.to_workspace_relative_path(abs_path), "TEMP/u1/c1/pic.png")
        self.assertEqual(
            self.workspace_service.to_workspace_relative_path("/x/y/Result/u1/c1/out.pdf"),
            "Result/u1/c1/out.pdf",
        )
        self.assertEqual(
            self.workspace_service.to_workspace_relative_path("TEMP/u1/c1/a.png"), "TEMP/u1/c1/a.png"
        )
        self.assertEqual(self.workspace_service.to_workspace_relative_path(""), "")

    def test_absolute_path_image_loads_after_normalization(self):
        """历史消息里存的是绝对路径，归一化后仍应读到图片。"""
        abs_path = os.path.abspath(self._write_workspace_image("u1", "c1", "abs.png", PNG_BYTES))
        loaded = self.multimodal.load_workspace_image(abs_path, "u1/c1")
        self.assertIsNotNone(loaded, "绝对路径归一化后应能读取")
        self.assertEqual(loaded["mime"], "image/png")

    def test_cross_user_and_absolute_paths_rejected(self):
        other = self._write_workspace_image("u2", "c2", "other.png", PNG_BYTES)
        self.assertIsNone(self.multimodal.load_workspace_image(other, "u1/c1"), "跨用户路径必须拒绝")
        self.assertIsNone(self.multimodal.load_workspace_image("/etc/passwd", "u1/c1"), "系统路径必须拒绝")

    def test_non_image_content_rejected_by_loader(self):
        path = self._write_workspace_image("u1", "c1", "notimage.png", b"MZ\x90\x00")
        self.assertIsNone(self.multimodal.load_workspace_image(path, "u1/c1"))

    # ── 工具注册 ──

    def test_image_reader_tool_is_registered_and_exposed(self):
        tools_module = importlib.import_module("tools")
        for exposure in ("agent", "plan_and_solve", "court"):
            self.assertIn("image_reader", tools_module.registry.names(exposure), f"{exposure} 未暴露 image_reader")

    def test_workspace_listing_marks_image_kind(self):
        import json as _json
        self._write_workspace_image("u1", "c1", "shot.png", PNG_BYTES)
        tools_module = importlib.import_module("tools")
        handler = tools_module.registry._by_name["list_workspace_files"].handler
        listed = _json.loads(handler({}, "u1/c1"))
        entry = next(item for item in listed if item["name"] == "shot.png")
        self.assertEqual(entry["kind"], "image", "列表需标出图片，模型才能决定读取")

    # ── 工具行为 ──

    def test_image_reader_returns_signal_and_base64_payload(self):
        path = self._write_workspace_image("u1", "c1", "view.png", PNG_BYTES)
        result = self._tool_handler()({"file_path": path}, "u1/c1")
        self.assertIsInstance(result, dict)
        self.assertIn(self.multimodal.IMAGE_SIGNAL_KEY, result)
        part = result[self.multimodal.IMAGE_SIGNAL_KEY]
        self.assertEqual(part["type"], "image_url")
        self.assertTrue(part["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]), PNG_BYTES)

    def test_image_reader_rejects_bad_input(self):
        handler = self._tool_handler()
        self.assertIsInstance(handler({}, "u1/c1"), str, "缺参数应返回错误文本")
        self.assertIsInstance(handler({"file_path": "TEMP/u1/c1/a.pdf"}, "u1/c1"), str, "非图片扩展名应拒绝")
        other = self._write_workspace_image("u2", "c2", "other.png", PNG_BYTES)
        self.assertIsInstance(handler({"file_path": other}, "u1/c1"), str, "跨用户路径应拒绝")

    # ── agent 循环：图片必须变成 user 消息里的 image_url ──

    def test_loop_injects_image_as_user_message(self):
        from services.agent_builder import build_agent

        path = self._write_workspace_image("u1", "c1", "scan2.png", PNG_BYTES)
        _Msg, _Resp = _make_message_class(), _make_response_class()

        class _ToolCall:
            id = "call_img_1"

            class function:  # noqa: N801
                name = "image_reader"
                arguments = '{"file_path": "' + path + '"}'

        def respond(round_number):
            if round_number == 1:
                return _Resp(_Msg("先看图", tool_calls=[_ToolCall()]))
            return _Resp(_Msg("<final_answer>图中是一张测试图。</final_answer>"))

        completions = _FakeCompletions(respond)
        _install_fake_client(self, self.function_calling, completions)

        agent = build_agent(
            "default",
            [{"role": "system", "content": "你是法律助手"}, {"role": "user", "content": "看一下工作区里的图片"}],
            "conv-mm", "u1/c1", use_ocp=False,
        )

        async def drive():
            async for _ in agent.run("看一下工作区里的图片", stream=False):
                pass

        asyncio.run(drive())

        self.assertEqual(len(completions.calls), 2, "应先调工具、再带图作答，共两轮")
        image_parts = _collect_image_parts(completions.calls[1])
        self.assertEqual(len(image_parts), 1, "第二轮调用必须带图片，否则模型看不到图")
        self.assertTrue(image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,"))

        tool_msgs = [m for m in completions.calls[1] if isinstance(m, dict) and m.get("role") == "tool"]
        self.assertTrue(tool_msgs, "缺少 tool 结果消息")
        for message in tool_msgs:
            self.assertIsInstance(message["content"], str, "tool 消息 content 必须是字符串")

    def test_loop_caps_images_per_turn(self):
        from services.agent_builder import build_agent

        path = self._write_workspace_image("u1", "c1", "loop.png", PNG_BYTES)
        _Msg, _Resp = _make_message_class(), _make_response_class()
        cap = self.multimodal.MAX_IMAGE_VIEWS_PER_TURN

        class _ToolCall:
            class function:  # noqa: N801
                name = "image_reader"
                arguments = '{"file_path": "' + path + '"}'

            def __init__(self, index):
                self.id = f"call_{index}"

        def respond(round_number):
            if round_number <= cap + 1:
                return _Resp(_Msg("再看", tool_calls=[_ToolCall(round_number)]))
            return _Resp(_Msg("<final_answer>看完。</final_answer>"))

        completions = _FakeCompletions(respond)
        _install_fake_client(self, self.function_calling, completions)

        agent = build_agent(
            "default",
            [{"role": "system", "content": "s"}, {"role": "user", "content": "看图"}],
            "conv-cap", "u1/c1", use_ocp=False,
        )

        async def drive():
            async for _ in agent.run("看图", stream=False):
                pass

        asyncio.run(drive())

        # 最后一轮的 messages 累积了本轮全部注入，用它统计实际图片数
        image_parts = _collect_image_parts(completions.calls[-1])
        self.assertLessEqual(len(image_parts), cap, f"图片数超过每轮上限 {cap}")
        self.assertGreater(len(image_parts), 0, "上限内至少应注入一张图片")

    def test_multiple_tool_calls_keep_tool_block_contiguous(self):
        """一次返回多个 tool_calls 时，图片必须等所有 tool 消息追加完再挂。

        否则 user 消息会插进 tool 消息块中间，触发端点报错
        "insufficient tool messages following tool_calls message"。
        """
        from services.agent_builder import build_agent

        path = self._write_workspace_image("u1", "c1", "pair.png", PNG_BYTES)
        _Msg, _Resp = _make_message_class(), _make_response_class()

        class _ImgCall:
            id = "call_img"

            class function:  # noqa: N801
                name = "image_reader"
                arguments = '{"file_path": "' + path + '"}'

        class _OtherCall:
            id = "call_other"

            class function:  # noqa: N801
                name = "list_workspace_files"
                arguments = "{}"

        def respond(round_number):
            if round_number == 1:
                return _Resp(_Msg("先看图并列出文件", tool_calls=[_ImgCall(), _OtherCall()]))
            return _Resp(_Msg("<final_answer>完成。</final_answer>"))

        completions = _FakeCompletions(respond)
        _install_fake_client(self, self.function_calling, completions)

        agent = build_agent(
            "default",
            [{"role": "system", "content": "s"}, {"role": "user", "content": "看图"}],
            "conv-pair", "u1/c1", use_ocp=False,
        )

        async def drive():
            async for _ in agent.run("看图", stream=False):
                pass

        asyncio.run(drive())

        messages = completions.calls[1]
        # 取最后一个 tool_calls 消息之后、到图片消息之前的区间，必须全是 tool 消息
        assistant_index = max(
            i for i, m in enumerate(messages)
            if isinstance(m, dict) and m.get("tool_calls")
        )
        following = messages[assistant_index + 1:]
        tool_ids = [
            m.get("tool_call_id") for m in following if isinstance(m, dict) and m.get("role") == "tool"
        ]
        self.assertEqual(
            tool_ids,
            ["call_img", "call_other"],
            f"tool 消息必须紧跟 tool_calls 且顺序一致，实际: {tool_ids}",
        )
        # 图片消息只能出现在所有 tool 消息之后
        image_index = next(
            i for i, m in enumerate(following)
            if isinstance(m, dict) and isinstance(m.get("content"), list)
        )
        self.assertGreater(image_index, len(tool_ids) - 1, "图片消息插进了 tool 消息块中间")

    def test_flatten_content_to_text_replaces_images(self):
        parts = [
            {"type": "text", "text": "说明"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ]
        flattened = self.multimodal.flatten_content_to_text(parts)
        self.assertIn("说明", flattened)
        self.assertIn("[图片]", flattened)
        self.assertNotIn("base64", flattened)


if __name__ == "__main__":
    unittest.main()
