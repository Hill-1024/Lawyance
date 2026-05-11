"""
模块描述：Agent 工具循环保护测试，验证可配置轮次限制和超限输出行为。
"""

import types
import os
import unittest


class _StreamToolCall:
    index = 0

    def model_dump(self, exclude_unset=True):
        return {
            "id": "call_stream",
            "type": "function",
            "function": {"name": "search_article", "arguments": "{\"query\":\"劳动\"}"},
        }


class _NonStreamToolCall:
    id = "call_non_stream"
    function = types.SimpleNamespace(name="search_article", arguments="{\"query\":\"劳动\"}")

    def model_dump(self, exclude_unset=True):
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


async def _one_stream_tool_chunk():
    delta = types.SimpleNamespace(reasoning_content=None, thought_signature=None, content=None, tool_calls=[_StreamToolCall()])
    yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


async def _content_stream(text: str):
    delta = types.SimpleNamespace(reasoning_content=None, thought_signature=None, content=text)
    yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


class AgentResourceGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

    async def test_default_streaming_stops_after_tool_round_limit(self):
        import agents.default as default_module
        from agents.default import DefaultAgent

        original_call = default_module.call

        async def fake_call(context, stream=False, include_tools=True):
            return _one_stream_tool_chunk()

        try:
            default_module.call = fake_call
            agent = DefaultAgent(memory=[{"role": "user", "content": "x"}], execute_tool=lambda name, args: "ok")
            agent.MAX_TOOL_ROUNDS = 2
            events = [event async for event in agent.run(stream=True)]
        finally:
            default_module.call = original_call

        self.assertTrue(any(event.get("type") == "error" and "最大轮次" in event.get("content", "") for event in events))

    async def test_default_non_streaming_returns_visible_message_after_limit(self):
        import agents.default as default_module
        from agents.default import DefaultAgent

        original_call = default_module.call

        async def fake_call(context, stream=False, include_tools=True):
            return types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()])

        try:
            default_module.call = fake_call
            agent = DefaultAgent(memory=[{"role": "user", "content": "x"}], execute_tool=lambda name, args: "ok")
            agent.MAX_NON_STREAM_ROUNDS = 2
            events = [event async for event in agent.run(stream=False)]
        finally:
            default_module.call = original_call

        self.assertEqual(events[-1]["type"], "content")
        self.assertIn("最大轮次", events[-1]["content"])

    async def test_default_non_streaming_has_no_round_limit_by_default(self):
        import agents.default as default_module
        from agents.default import DefaultAgent

        original_call = default_module.call
        calls = {"count": 0}

        async def fake_call(context, stream=False, include_tools=True):
            calls["count"] += 1
            if calls["count"] <= 12:
                return types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()])
            return types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None)

        try:
            default_module.call = fake_call
            agent = DefaultAgent(memory=[{"role": "user", "content": "x"}], use_ocp=False, execute_tool=lambda name, args: "ok")
            events = [event async for event in agent.run(stream=False)]
        finally:
            default_module.call = original_call

        self.assertEqual(calls["count"], 13)
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_default_non_streaming_emits_hidden_tool_history_trace(self):
        import agents.default as default_module
        from agents.default import DefaultAgent

        original_call = default_module.call
        responses = [
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()]),
            types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, include_tools=True):
            return responses.pop(0)

        try:
            default_module.call = fake_call
            agent = DefaultAgent(memory=[{"role": "user", "content": "x"}], use_ocp=False, execute_tool=lambda name, args: "工具结果")
            events = [event async for event in agent.run(stream=False)]
        finally:
            default_module.call = original_call

        traces = [event["content"][0] for event in events if event.get("type") == "history_trace"]
        self.assertTrue(any(msg.get("role") == "assistant" and msg.get("tool_calls") for msg in traces))
        self.assertTrue(any(msg.get("role") == "tool" and msg.get("tool_call_id") == "call_non_stream" for msg in traces))
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_react_max_steps_outputs_visible_content(self):
        import agents.react as react_module
        from agents.react import ReActAgent

        original_call = react_module.call

        async def fake_call(context, stream=False, include_tools=True):
            return _content_stream("Thought: 查找资料\nAction: search_article[劳动合同]")

        try:
            react_module.call = fake_call
            agent = ReActAgent("", lambda name, args: "观察", max_steps=1)
            events = [event async for event in agent.run("问题")]
        finally:
            react_module.call = original_call

        self.assertTrue(any(event.get("type") == "content" and "最大步数" in event.get("content", "") for event in events))

    async def test_plan_and_solve_no_plan_outputs_visible_content(self):
        import agents.plan_and_solve as plan_module
        from agents.plan_and_solve import PlanAndSolveAgent

        original_call = plan_module.call

        async def fake_call(context, stream=False, include_tools=True):
            return _content_stream("无法规划")

        try:
            plan_module.call = fake_call
            agent = PlanAndSolveAgent()
            events = [event async for event in agent.run("问题")]
        finally:
            plan_module.call = original_call

        self.assertTrue(any(event.get("type") == "content" and "无法生成有效行动计划" in event.get("content", "") for event in events))


if __name__ == "__main__":
    unittest.main()
