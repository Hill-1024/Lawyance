"""
模块描述：上下文 token usage 捕获、传递与压缩触发回归测试。
"""

import importlib
import os
import types
import unittest
from unittest import mock


class ContextUsageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")

    async def test_non_stream_call_records_usage_on_success_and_tool_choice_fallback(self):
        context_usage = importlib.import_module("services.context_usage")
        function_calling = importlib.reload(importlib.import_module("function_calling"))
        original_create = function_calling.client.chat.completions.create

        async def fake_create_success(**_kwargs):
            message = types.SimpleNamespace(content="ok")
            usage = types.SimpleNamespace(
                prompt_tokens=123,
                prompt_tokens_details=types.SimpleNamespace(cached_tokens=23),
            )
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=usage)

        token, accumulator = context_usage.set_current_context_usage_accumulator()
        try:
            function_calling.client.chat.completions.create = fake_create_success
            await function_calling.call([{"role": "user", "content": "hello"}], stream=False, include_tools=False)
        finally:
            function_calling.client.chat.completions.create = original_create
            context_usage.reset_current_context_usage_accumulator(token)

        self.assertEqual(accumulator.prompt_tokens, 123)
        self.assertEqual(accumulator.cached_tokens, 23)

        calls = 0

        async def fake_create_fallback(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise Exception("tool_choice does not support forced mode")
            message = types.SimpleNamespace(content="ok")
            usage = types.SimpleNamespace(prompt_tokens=234, prompt_cache_hit_tokens=34)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=usage)

        token, accumulator = context_usage.set_current_context_usage_accumulator()
        try:
            function_calling.client.chat.completions.create = fake_create_fallback
            await function_calling.call(
                [{"role": "user", "content": "hello"}],
                stream=False,
                tools_override=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
                tool_choice={"type": "function", "function": {"name": "lookup"}},
            )
        finally:
            function_calling.client.chat.completions.create = original_create
            context_usage.reset_current_context_usage_accumulator(token)

        self.assertEqual(calls, 2)
        self.assertEqual(accumulator.prompt_tokens, 234)
        self.assertEqual(accumulator.cached_tokens, 34)

    async def test_stream_usage_only_chunk_is_recorded_without_breaking_content(self):
        context_usage = importlib.import_module("services.context_usage")
        tool_loop = importlib.reload(importlib.import_module("agents.tool_loop"))
        original_call = tool_loop.call

        async def fake_call(*_args, **_kwargs):
            async def stream():
                yield types.SimpleNamespace(
                    usage=types.SimpleNamespace(prompt_tokens=345, cache_read_input_tokens=45),
                    choices=[],
                )
                yield types.SimpleNamespace(
                    choices=[
                        types.SimpleNamespace(
                            delta=types.SimpleNamespace(content="<final_answer>ok</final_answer>")
                        )
                    ]
                )

            return stream()

        token, accumulator = context_usage.set_current_context_usage_accumulator()
        try:
            tool_loop.call = fake_call
            agent = tool_loop.ToolLoopAgent(memory=[{"role": "user", "content": "hi"}], use_ocp=False)
            events = [event async for event in agent.run(stream=True)]
        finally:
            tool_loop.call = original_call
            context_usage.reset_current_context_usage_accumulator(token)

        self.assertEqual(accumulator.prompt_tokens, 345)
        self.assertTrue(any(event.get("content") == "ok" for event in events))

    async def test_run_agent_once_returns_usage_from_agent_scope_only(self):
        context_usage = importlib.import_module("services.context_usage")
        chat_pipeline = importlib.import_module("services.chat_pipeline")

        class FakeAgent:
            async def run(self, _content, stream=False):
                context_usage.record_context_usage(100, 10, 90)
                yield {"type": "content", "content": "ok"}

        context_usage.record_context_usage(999999, 0, 999999)
        prepared = chat_pipeline.PreparedChatTurn(
            content="hello",
            session_id="conv",
            stream=False,
            agent_mode="default",
            workspace_scope="user/conv",
            turn_id="turn_test",
            agent=FakeAgent(),
        )

        with mock.patch("services.chat_pipeline.persist_turn", return_value={}):
            result = await chat_pipeline.run_agent_once(prepared)

        self.assertEqual(result["context_usage"]["prompt_tokens"], 100)
        self.assertEqual(result["reply"], "ok")

    async def test_compress_history_uses_last_context_tokens_and_summary_budget(self):
        history_service = importlib.import_module("services.history")
        original_call = history_service.call

        captured_summary = {}

        async def fake_call(context, stream=False, include_tools=True):
            captured_summary["content"] = context[-1]["content"]
            return types.SimpleNamespace(content='{"stable_facts":["甲公司已付款"],"completed_steps":["已读取合同"],"tool_evidence":["search_article 返回民法典第五百七十七条"],"active_files":["合同.pdf"],"open_questions":["付款日期待核实"],"must_keep_constraints":["引用依据"],"next_likely_action":"补充案例检索"}')

        large_messages = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": f"消息{index} " + ("旧" * 30000)}
            for index in range(12)
        ]
        history = [{"role": "system", "content": "system"}] + large_messages

        try:
            history_service.call = fake_call
            compressed = await history_service.compress_history(history, last_context_tokens=500001)
        finally:
            history_service.call = original_call

        self.assertLess(len(compressed), len(history) + 3)
        compressed_text = "\n".join(str(msg.get("content", "")) for msg in compressed)
        self.assertIn("[前情提要]", compressed_text)
        self.assertIn("稳定事实", compressed_text)
        self.assertIn("甲公司已付款", compressed_text)
        self.assertIn("下一步: 补充案例检索", compressed_text)
        self.assertIn("旧" * 300, captured_summary["content"])

        unchanged = await history_service.compress_history(
            [{"role": "system", "content": "system"}, {"role": "user", "content": "short"}],
            last_context_tokens=500000,
        )
        self.assertEqual(len(unchanged), 2)

    async def test_history_summary_invalid_json_falls_back_to_plain_summary(self):
        history_service = importlib.import_module("services.history")
        original_call = history_service.call

        async def fake_call(context, stream=False, include_tools=True):
            return types.SimpleNamespace(content="普通摘要")

        history = [{"role": "system", "content": "system"}] + [
            {"role": "user", "content": "长" * 60000}
            for _ in range(10)
        ]

        try:
            history_service.call = fake_call
            compressed = await history_service.compress_history(history)
        finally:
            history_service.call = original_call

        compressed_text = "\n".join(str(msg.get("content", "")) for msg in compressed)
        self.assertIn("[前情提要]: 普通摘要", compressed_text)

    async def test_missing_last_context_tokens_uses_local_estimate_fallback(self):
        history_service = importlib.import_module("services.history")
        original_call = history_service.call

        async def fake_call(context, stream=False, include_tools=True):
            return types.SimpleNamespace(content="摘要")

        history = [{"role": "system", "content": "system"}] + [
            {"role": "user", "content": "长" * 60000}
            for _ in range(10)
        ]

        try:
            history_service.call = fake_call
            compressed = await history_service.compress_history(history)
        finally:
            history_service.call = original_call

        self.assertTrue(any("[前情提要]" in str(msg.get("content", "")) for msg in compressed))


if __name__ == "__main__":
    unittest.main()
