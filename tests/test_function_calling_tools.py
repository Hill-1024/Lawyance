"""
模块描述：模型调用工具加载测试，验证 function_calling 按静态工具边界传递 tools。
"""

import os
import types
import unittest


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


if __name__ == "__main__":
    unittest.main()
