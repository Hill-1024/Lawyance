"""
模块描述：Agent 工具循环保护测试，验证可配置轮次限制和工具消息配对。
"""

import os
import types
import unittest


class _NonStreamToolCall:
    def __init__(self, name="search_article", arguments='{"query":"劳动"}', call_id="call_non_stream"):
        self.id = call_id
        self.function = types.SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self, exclude_unset=True):
        del exclude_unset
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


class AgentResourceGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

    async def test_tool_loop_non_streaming_returns_visible_message_after_limit(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call

        async def fake_call(context, stream=False, **kwargs):
            return types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()])

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "x"}],
                use_ocp=False,
                execute_tool=lambda name, args: "ok",
                max_rounds=2,
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(events[-1]["type"], "content")
        self.assertIn("最大轮次", events[-1]["content"])

    async def test_tool_loop_round_limit_can_be_disabled_explicitly(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        calls = {"count": 0}

        async def fake_call(context, stream=False, **kwargs):
            calls["count"] += 1
            if calls["count"] <= 12:
                return types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()])
            return types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "x"}],
                use_ocp=False,
                execute_tool=lambda name, args: "ok",
                max_rounds=None,
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(calls["count"], 13)
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_tool_loop_does_not_limit_rounds_by_default(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        calls = {"count": 0}

        async def fake_call(context, stream=False, **kwargs):
            calls["count"] += 1
            if calls["count"] <= 12:
                return types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()])
            return types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "x"}],
                use_ocp=False,
                execute_tool=lambda name, args: "ok",
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(calls["count"], 13)
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_tool_loop_emits_hidden_tool_history_trace(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        responses = [
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()]),
            types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, **kwargs):
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "x"}],
                use_ocp=False,
                execute_tool=lambda name, args: "工具结果",
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        traces = [event["content"][0] for event in events if event.get("type") == "history_trace"]
        self.assertTrue(any(msg.get("role") == "assistant" and msg.get("tool_calls") for msg in traces))
        self.assertTrue(any(msg.get("role") == "tool" and msg.get("tool_call_id") == "call_non_stream" for msg in traces))
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_tool_loop_pauses_for_user_choice_request(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        calls = {"count": 0}

        async def fake_call(context, stream=False, **kwargs):
            calls["count"] += 1
            return types.SimpleNamespace(
                content="",
                tool_calls=[
                    _NonStreamToolCall(
                        name="ask_user",
                        arguments='{"question":"下一步怎么做？","options":[{"label":"检索"},{"label":"起草"}]}',
                        call_id="call_ask_user",
                    )
                ],
            )

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "x"}],
                use_ocp=False,
                execute_tool=lambda name, args: {
                    "acknowledged": True,
                    "question": args["question"],
                    "options": [
                        {"id": "option_1", "label": "检索", "value": "检索"},
                        {"id": "option_2", "label": "起草", "value": "起草"},
                    ],
                    "allow_free_text": True,
                    "free_text_label": "自定义",
                },
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(calls["count"], 1)
        choice_events = [event for event in events if event.get("type") == "user_choice_request"]
        self.assertEqual(len(choice_events), 1)
        self.assertEqual(choice_events[0]["content"]["question"], "下一步怎么做？")
        self.assertEqual([option["label"] for option in choice_events[0]["content"]["options"]], ["检索", "起草"])
        self.assertTrue(choice_events[0]["content"]["allow_ignore"])
        self.assertEqual(choice_events[0]["content"]["ignore_label"], "忽略此问题")
        self.assertFalse(any(event.get("type") == "content" for event in events))

    async def test_execution_policy_repairs_missing_legal_evidence_once(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        memory = [{"role": "user", "content": "乙公司违约怎么起诉？"}]
        responses = [
            types.SimpleNamespace(content="<final_answer>可以起诉。</final_answer>", tool_calls=None),
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="match_legal_case", arguments='{"keywords":["违约责任"]}')]),
            types.SimpleNamespace(content="<final_answer>已根据案例补充。</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, **kwargs):
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=memory,
                use_ocp=False,
                execute_tool=lambda name, args: "工具结果",
                execution_policy={"requires_legal_evidence": True, "soft_repair_enabled": True},
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(events[-1], {"type": "content", "content": "已根据案例补充。"})
        self.assertTrue(any(msg.get("role") == "system" and "execution_policy_repair" in msg.get("content", "") for msg in memory))
        self.assertFalse(responses)

    async def test_execution_policy_does_not_repair_when_legal_tool_was_used(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        memory = [{"role": "user", "content": "找法条"}]
        responses = [
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="get_article", arguments='{"query":"违约责任"}')]),
            types.SimpleNamespace(content="<final_answer>完成</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, **kwargs):
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=memory,
                use_ocp=False,
                execute_tool=lambda name, args: "法条结果",
                execution_policy={"requires_legal_evidence": True, "soft_repair_enabled": True},
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(events[-1], {"type": "content", "content": "完成"})
        self.assertFalse(any(msg.get("role") == "system" and "execution_policy_repair" in msg.get("content", "") for msg in memory))

    async def test_execution_policy_repairs_missing_file_read_once(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        responses = [
            types.SimpleNamespace(content="<final_answer>文件看完了。</final_answer>", tool_calls=None),
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="list_workspace_files", arguments="{}")]),
            types.SimpleNamespace(content="<final_answer>已确认文件列表。</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, **kwargs):
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "分析上传的合同"}],
                use_ocp=False,
                execute_tool=lambda name, args: "文件列表",
                execution_policy={"requires_file_read": True, "requires_workspace_listing": True, "soft_repair_enabled": True},
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(events[-1], {"type": "content", "content": "已确认文件列表。"})
        self.assertFalse(responses)

    async def test_plan_and_solve_repairs_plan_steps_without_business_tool(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent, plan_and_solve_tool_choice_policy

        original_call = tool_loop_module.call
        responses = [
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="submit_plan", arguments='{"steps":["检索相关法条"]}', call_id="call_plan")]),
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="submit_final_answer", arguments='{"answer":"直接回答"}', call_id="call_final_1")]),
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="search_article", arguments='{"query":"违约责任"}', call_id="call_search")]),
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="submit_final_answer", arguments='{"answer":"补证后回答"}', call_id="call_final_2")]),
        ]

        async def fake_call(context, stream=False, **kwargs):
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "违约怎么处理？"}],
                use_ocp=False,
                execute_tool=lambda name, args: {"ok": True, "tool": name},
                mode="plan_and_solve",
                final_answer_source="tool_arg",
                tool_choice_policy=plan_and_solve_tool_choice_policy,
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(events[-1], {"type": "content", "content": "补证后回答"})
        self.assertFalse(responses)


if __name__ == "__main__":
    unittest.main()
