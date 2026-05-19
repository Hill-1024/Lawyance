"""
模块描述：模型调用工具加载测试，验证 function_calling 按静态工具边界传递 tools。
"""

import os
import types
import unittest
from datetime import datetime
from unittest import mock


class FunctionCallingToolLoadingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")

    async def test_call_passes_imported_tools_directly(self):
        import function_calling

        original_tools = function_calling.tools
        original_create = function_calling.client.chat.completions.create
        captured = {}
        sentinel_tools = [
            {
                "type": "function",
                "function": {
                    "name": "sentinel_tool",
                    "description": "test",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        async def fake_create(**kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        try:
            function_calling.tools = sentinel_tools
            function_calling.client.chat.completions.create = fake_create

            await function_calling.call(
                [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "hello"},
                ],
                stream=False,
            )
        finally:
            function_calling.tools = original_tools
            function_calling.client.chat.completions.create = original_create

        self.assertIs(captured["tools"], sentinel_tools)
        self.assertEqual(captured["tool_choice"], "auto")

    async def test_call_can_disable_tools_for_internal_tasks(self):
        import function_calling

        original_create = function_calling.client.chat.completions.create
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        try:
            function_calling.client.chat.completions.create = fake_create
            await function_calling.call(
                [
                    {"role": "system", "content": "summary"},
                    {"role": "user", "content": "hello"},
                ],
                stream=False,
                include_tools=False,
            )
        finally:
            function_calling.client.chat.completions.create = original_create

        self.assertNotIn("tools", captured)
        self.assertNotIn("tool_choice", captured)

    async def test_call_preserves_multiple_system_messages_in_order(self):
        import function_calling

        original_create = function_calling.client.chat.completions.create
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        try:
            function_calling.client.chat.completions.create = fake_create
            await function_calling.call(
                [
                    {"role": "system", "content": "system A"},
                    {"role": "user", "content": "hello"},
                    {"role": "system", "content": "system B"},
                    {"role": "system", "content": "system C"},
                    {"role": "user", "content": "again"},
                ],
                stream=False,
                include_tools=False,
            )
        finally:
            function_calling.client.chat.completions.create = original_create

        messages = captured["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "system", "system", "user", "user"])
        self.assertTrue(messages[0]["content"].startswith("system A\n\n【当前系统"))
        self.assertEqual(messages[1]["content"], "system B")
        self.assertEqual(messages[2]["content"], "system C")
        self.assertEqual(messages[3]["content"], "hello")
        self.assertEqual(messages[4]["content"], "again")

    async def test_call_keeps_front_loaded_system_messages_in_order(self):
        import function_calling

        original_create = function_calling.client.chat.completions.create
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        try:
            function_calling.client.chat.completions.create = fake_create
            await function_calling.call(
                [
                    {"role": "system", "content": "prefix"},
                    {"role": "system", "content": "memory"},
                    {"role": "system", "content": "recap"},
                    {"role": "user", "content": "hello"},
                ],
                stream=False,
                include_tools=False,
            )
        finally:
            function_calling.client.chat.completions.create = original_create

        messages = captured["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "system", "system", "user"])
        self.assertTrue(messages[0]["content"].startswith("prefix\n\n【当前系统"))
        self.assertEqual(messages[1]["content"], "memory")
        self.assertEqual(messages[2]["content"], "recap")
        self.assertEqual(messages[3]["content"], "hello")

    async def test_call_appends_date_only_to_first_system(self):
        import function_calling

        original_create = function_calling.client.chat.completions.create
        captured = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        try:
            function_calling.client.chat.completions.create = fake_create
            with mock.patch("function_calling._now", return_value=datetime(2026, 5, 19, 10, 30, 0)):
                await function_calling.call(
                    [
                        {"role": "system", "content": "prefix"},
                        {"role": "system", "content": "memory"},
                        {"role": "system", "content": "recap"},
                        {"role": "user", "content": "hello"},
                    ],
                    stream=False,
                    include_tools=False,
                )
        finally:
            function_calling.client.chat.completions.create = original_create

        messages = captured["messages"]
        self.assertEqual(messages[0]["content"], "prefix\n\n【当前系统日期】：2026-05-19 星期二")
        self.assertEqual(messages[1]["content"], "memory")
        self.assertEqual(messages[2]["content"], "recap")

    async def test_first_system_byte_stable_within_same_day_and_changes_across_days(self):
        import function_calling

        original_create = function_calling.client.chat.completions.create
        captured_messages = []
        context = [
            {"role": "system", "content": "prefix"},
            {"role": "system", "content": "memory"},
            {"role": "system", "content": "recap"},
            {"role": "user", "content": "hello"},
        ]

        async def fake_create(**kwargs):
            captured_messages.append(kwargs["messages"])
            message = types.SimpleNamespace(content="ok")
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

        try:
            function_calling.client.chat.completions.create = fake_create
            with mock.patch("function_calling._now", return_value=datetime(2026, 5, 19, 10, 30, 0)):
                await function_calling.call(context, stream=False, include_tools=False)
            with mock.patch("function_calling._now", return_value=datetime(2026, 5, 19, 23, 59, 59)):
                await function_calling.call(context, stream=False, include_tools=False)
            with mock.patch("function_calling._now", return_value=datetime(2026, 5, 20, 0, 0, 1)):
                await function_calling.call(context, stream=False, include_tools=False)
        finally:
            function_calling.client.chat.completions.create = original_create

        self.assertEqual(captured_messages[0][0]["content"], captured_messages[1][0]["content"])
        self.assertNotEqual(captured_messages[1][0]["content"], captured_messages[2][0]["content"])
        self.assertEqual(context[0]["content"], "prefix")

    def test_extract_cache_stats_uses_stable_field_priority(self):
        import function_calling

        prompt, cached, miss = function_calling._extract_cache_stats(
            types.SimpleNamespace(
                prompt_tokens=100,
                prompt_tokens_details=types.SimpleNamespace(cached_tokens=40),
                prompt_cache_hit_tokens=30,
                cache_read_input_tokens=20,
            )
        )
        self.assertEqual((prompt, cached, miss), (100, 40, 60))

        prompt, cached, miss = function_calling._extract_cache_stats(
            types.SimpleNamespace(
                prompt_tokens=100,
                prompt_tokens_details=types.SimpleNamespace(cached_tokens=0),
                prompt_cache_hit_tokens=30,
                cache_read_input_tokens=20,
            )
        )
        self.assertEqual((prompt, cached, miss), (100, 30, 70))

        prompt, cached, miss = function_calling._extract_cache_stats(
            types.SimpleNamespace(prompt_tokens=100, cache_read_input_tokens=20)
        )
        self.assertEqual((prompt, cached, miss), (100, 20, 80))

    async def test_call_adds_stream_options_without_consuming_stream(self):
        import function_calling

        original_create = function_calling.client.chat.completions.create
        captured = {}
        stream_response = object()

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return stream_response

        try:
            function_calling.client.chat.completions.create = fake_create
            with mock.patch("function_calling._now", return_value=datetime(2026, 5, 19, 10, 30, 0)):
                response = await function_calling.call(
                    [{"role": "system", "content": "prefix"}, {"role": "user", "content": "hello"}],
                    stream=True,
                    include_tools=False,
                )
        finally:
            function_calling.client.chat.completions.create = original_create

        self.assertIs(response, stream_response)
        self.assertEqual(captured["stream_options"], {"include_usage": True})


if __name__ == "__main__":
    unittest.main()
