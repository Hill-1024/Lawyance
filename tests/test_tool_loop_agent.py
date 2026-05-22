"""
模块描述：统一 ToolLoopAgent 行为测试，覆盖默认模式与 Plan-and-Solve 控制面流程。
"""

import copy
import json
import os
import types
import unittest


class _ToolCall:
    def __init__(self, name: str, arguments: str, call_id: str):
        self.id = call_id
        self.function = types.SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self, exclude_unset=True):
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


class ToolLoopAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

    async def test_default_tagged_text_final_answer(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call

        async def fake_call(context, stream=False, **kwargs):
            return types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(memory=[{"role": "user", "content": "问题"}], use_ocp=False)
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_stream_peer_closed_falls_back_to_non_stream_round(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        call_modes = []

        class BrokenStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise RuntimeError("peer closed connection without sending complete message body (incomplete chunked read)")

        async def fake_call(context, stream=False, **kwargs):
            call_modes.append(stream)
            if stream:
                return BrokenStream()
            return types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(memory=[{"role": "user", "content": "问题"}], use_ocp=False)
            events = [event async for event in agent.run(stream=True)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(call_modes, [True, False])
        self.assertTrue(any("非流式重试" in event.get("content", "") for event in events))
        self.assertEqual(events[-1], {"type": "content_replace", "content": "完成"})

    async def test_plan_and_solve_state_machine_and_final_answer(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent, plan_and_solve_tool_choice_policy
        from mcps import plan_and_solve_tools

        original_call = tool_loop_module.call
        captured = []
        responses = [
            types.SimpleNamespace(
                content="",
                tool_calls=[_ToolCall("submit_plan", json.dumps({"steps": ["检索依据", "整理答案"]}, ensure_ascii=False), "call_plan")],
            ),
            types.SimpleNamespace(
                content="",
                tool_calls=[_ToolCall("search_article", json.dumps({"query": "劳动合同解除"}, ensure_ascii=False), "call_search")],
            ),
            types.SimpleNamespace(content="已经取得依据，可以汇总。", tool_calls=None),
            types.SimpleNamespace(
                content="",
                tool_calls=[_ToolCall("submit_final_answer", json.dumps({"answer": "最终答案"}, ensure_ascii=False), "call_final")],
            ),
        ]

        async def fake_call(context, stream=False, **kwargs):
            captured.append({
                "context": copy.deepcopy(context),
                "tools_override": kwargs.get("tools_override"),
                "tool_choice": kwargs.get("tool_choice"),
            })
            return responses.pop(0)

        def execute_tool(name, args):
            if name == "submit_plan":
                return {"acknowledged": True, "steps": args.get("steps", [])}
            if name == "submit_final_answer":
                return {"acknowledged": True}
            return "《劳动合同法》相关内容"

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "问题"}],
                use_ocp=False,
                execute_tool=execute_tool,
                mode="plan_and_solve",
                tools=plan_and_solve_tools,
                final_answer_source="tool_arg",
                tool_choice_policy=plan_and_solve_tool_choice_policy,
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(len(captured), 4)
        self.assertTrue(all(call["tools_override"] is plan_and_solve_tools for call in captured))
        self.assertEqual(captured[0]["tool_choice"]["function"]["name"], "submit_plan")
        self.assertEqual(captured[1]["tool_choice"], "auto")
        self.assertEqual(captured[2]["tool_choice"], "auto")
        self.assertEqual(captured[3]["tool_choice"]["function"]["name"], "submit_final_answer")
        self.assertTrue(any(event.get("thought_type") == "plan" and "检索依据" in event.get("content", "") for event in events))
        self.assertEqual([event for event in events if event.get("type") == "memory_candidate"], [{"type": "memory_candidate", "content": "最终答案"}])
        self.assertEqual(events[-1], {"type": "content", "content": "最终答案"})
        self.assertEqual(captured[0]["context"][0], captured[1]["context"][0])
        self.assertEqual(captured[1]["context"][0], captured[2]["context"][0])
        self.assertEqual(captured[2]["context"][0], captured[3]["context"][0])

    async def test_submit_final_answer_terminates_without_extra_call(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent, plan_and_solve_tool_choice_policy

        original_call = tool_loop_module.call
        calls = {"count": 0}
        responses = [
            types.SimpleNamespace(
                content="",
                tool_calls=[_ToolCall("submit_plan", json.dumps({"steps": ["一步"]}, ensure_ascii=False), "call_plan")],
            ),
            types.SimpleNamespace(
                content="",
                tool_calls=[_ToolCall("submit_final_answer", json.dumps({"answer": "立即完成"}, ensure_ascii=False), "call_final")],
            ),
        ]

        async def fake_call(context, stream=False, **kwargs):
            calls["count"] += 1
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "问题"}],
                use_ocp=False,
                execute_tool=lambda name, args: {"acknowledged": True, "steps": args.get("steps", [])} if name == "submit_plan" else {"acknowledged": True},
                mode="plan_and_solve",
                final_answer_source="tool_arg",
                tool_choice_policy=plan_and_solve_tool_choice_policy,
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(calls["count"], 2)
        self.assertEqual(events[-1], {"type": "content", "content": "立即完成"})

    async def test_invalid_json_arguments_are_returned_as_tool_message(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        captured = []
        responses = [
            types.SimpleNamespace(content="", tool_calls=[_ToolCall("search_article", "{bad-json", "call_bad")]),
            types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, **kwargs):
            captured.append(copy.deepcopy(context))
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "问题"}],
                use_ocp=False,
                execute_tool=lambda name, args: "不应执行",
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        tool_messages = [message for message in captured[1] if message.get("role") == "tool"]
        self.assertTrue(tool_messages)
        self.assertIn("invalid_json_arguments", tool_messages[-1]["content"])
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_non_stream_tool_call_preserves_reasoning_content_for_next_round(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        captured = []
        responses = [
            types.SimpleNamespace(
                content="",
                reasoning_content="需要先检索定义",
                thought_signature="sig-1",
                tool_calls=[_ToolCall("search_article", json.dumps({"query": "合同定义"}, ensure_ascii=False), "call_search")],
            ),
            types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, **kwargs):
            captured.append(copy.deepcopy(context))
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "问题"}],
                use_ocp=False,
                execute_tool=lambda name, args: "检索结果",
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        assistant_messages = [message for message in captured[1] if message.get("role") == "assistant"]
        self.assertTrue(assistant_messages)
        self.assertEqual(assistant_messages[-1]["reasoning_content"], "需要先检索定义")
        self.assertEqual(assistant_messages[-1]["thought_signature"], "sig-1")
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})


if __name__ == "__main__":
    unittest.main()
