"""
模块描述：Agent 工具循环保护测试，验证可配置轮次限制和工具消息配对。
"""

import os
import threading
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

    async def test_sync_tool_execution_is_offloaded_from_event_loop_thread(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        main_thread = threading.get_ident()
        execution_threads: list[int] = []
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
                execute_tool=lambda _name, _args: execution_threads.append(threading.get_ident()) or "ok",
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(events[-1], {"type": "content", "content": "完成"})
        self.assertEqual(len(execution_threads), 1)
        self.assertNotEqual(execution_threads[0], main_thread)

    async def test_tool_loop_round_limit_cannot_be_disabled_explicitly(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        calls = {"count": 0}

        async def fake_call(context, stream=False, **kwargs):
            calls["count"] += 1
            return types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall()])

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

        self.assertEqual(calls["count"], ToolLoopAgent.HARD_MAX_ROUNDS)
        self.assertEqual(events[-1]["type"], "content")
        self.assertEqual(events[-1]["code"], "tool_round_limit")
        self.assertEqual(events[-1]["max_rounds"], ToolLoopAgent.HARD_MAX_ROUNDS)

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

        self.assertEqual(agent.max_rounds, ToolLoopAgent.HARD_MAX_ROUNDS)
        self.assertEqual(calls["count"], 13)
        self.assertEqual(events[-1], {"type": "content", "content": "完成"})

    async def test_tool_loop_streaming_round_limit_has_stable_error_code(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        calls = {"count": 0}

        async def fake_call(context, stream=False, **kwargs):
            calls["count"] += 1

            async def chunks():
                tool_call = _NonStreamToolCall(call_id=f"call_stream_{calls['count']}")
                tool_call.index = 0
                delta = types.SimpleNamespace(
                    reasoning_content=None,
                    thought_signature=None,
                    content=None,
                    tool_calls=[tool_call],
                )
                yield types.SimpleNamespace(usage=None, choices=[types.SimpleNamespace(delta=delta)])

            return chunks()

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "x"}],
                use_ocp=False,
                execute_tool=lambda name, args: "ok",
                max_rounds=2,
            )
            events = [event async for event in agent.run(stream=True)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(calls["count"], 2)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "tool_round_limit")
        self.assertEqual(events[-1]["max_rounds"], 2)

    async def test_hidden_control_tool_does_not_trigger_special_branch_before_authorization(self):
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent
        from tools import registry

        original_call = tool_loop_module.call
        executed = []
        responses = [
            types.SimpleNamespace(
                content="",
                tool_calls=[_NonStreamToolCall(
                    name="submit_final_answer",
                    arguments='{"answer":"越权答案"}',
                    call_id="call_hidden_final",
                )],
            ),
            types.SimpleNamespace(content="<final_answer>正常答案</final_answer>", tool_calls=None),
        ]

        async def fake_call(context, stream=False, **kwargs):
            return responses.pop(0)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=[{"role": "user", "content": "x"}],
                use_ocp=False,
                execute_tool=lambda name, args: executed.append(name) or {"acknowledged": True},
                mode="default",
                tools=registry.schemas("agent"),
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(executed, [])
        self.assertEqual(events[-1], {"type": "content", "content": "正常答案"})
        denied_messages = [
            message
            for event in events if event.get("type") == "history_trace"
            for message in event.get("content", [])
            if message.get("role") == "tool" and message.get("name") == "submit_final_answer"
        ]
        self.assertEqual(len(denied_messages), 1)
        self.assertIn("tool_not_authorized", denied_messages[0]["content"])

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

    async def test_final_answer_without_expected_tools_is_emitted_asis(self):
        """缺口修复已移除：未按执行策略调用工具时，也不得再插入提醒或重跑模型。

        这条曾经在提交最终回答后注入 system 提醒并重跑一轮，把已经写完的回答
        替换成了 L0-1 拒绝模板；现在首轮最终回答直接采用。
        """
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent

        original_call = tool_loop_module.call
        memory = [{"role": "user", "content": "乙公司违约怎么起诉？"}]
        calls = {"count": 0}

        async def fake_call(context, stream=False, **kwargs):
            calls["count"] += 1
            return types.SimpleNamespace(content="<final_answer>可以起诉。</final_answer>", tool_calls=None)

        try:
            tool_loop_module.call = fake_call
            agent = ToolLoopAgent(
                memory=memory,
                use_ocp=False,
                execute_tool=lambda name, args: "工具结果",
            )
            events = [event async for event in agent.run(stream=False)]
        finally:
            tool_loop_module.call = original_call

        self.assertEqual(calls["count"], 1, "首轮最终回答后不应再重跑模型")
        self.assertEqual(events[-1], {"type": "content", "content": "可以起诉。"})
        self.assertFalse(any(msg.get("role") == "system" for msg in memory), "不应再向对话注入提醒")

    async def test_plan_and_solve_submitted_answer_is_emitted_without_extra_round(self):
        """Plan-and-Solve 提交最终答案后直接出结果，不再因执行缺口重跑。"""
        import agents.tool_loop as tool_loop_module
        from agents.tool_loop import ToolLoopAgent, plan_and_solve_tool_choice_policy

        original_call = tool_loop_module.call
        responses = [
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="submit_plan", arguments='{"steps":["检索相关法条"]}', call_id="call_plan")]),
            types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(name="submit_final_answer", arguments='{"answer":"直接回答"}', call_id="call_final_1")]),
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

        self.assertEqual(events[-1], {"type": "content", "content": "直接回答"})
        self.assertFalse(responses, "提交最终答案后不应再调用模型")

    async def test_completed_answer_is_terminal_across_output_paths(self):
        """终轮预算下仍交付答案：覆盖流式、控制面与 OCP 的所有组合。"""
        from unittest.mock import patch
        from agents.tool_loop import ToolLoopAgent, plan_and_solve_tool_choice_policy

        answer = "现有信息不足以确认责任，需要进一步核验。"
        for stream in (False, True):
            for planned in (False, True):
                for reviewed in (False, True):
                    with self.subTest(stream=stream, planned=planned, reviewed=reviewed):
                        responses = []
                        if planned:
                            responses.extend([
                                types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(
                                    name="submit_plan", arguments='{"steps":["检索法条并读取附件"]}', call_id="plan")]),
                                types.SimpleNamespace(content="", tool_calls=[_NonStreamToolCall(
                                    name="submit_final_answer", arguments='{"answer":"' + answer + '"}', call_id="final")]),
                            ])
                        else:
                            responses.append(types.SimpleNamespace(
                                content="<final_answer>" + answer + "</final_answer>", tool_calls=None))
                        expected_calls = len(responses)
                        review_inputs = []

                        class Review:
                            async def complete(self, content):
                                review_inputs.append(content)
                                return content

                            async def stream(self, content):
                                review_inputs.append(content)
                                yield {"type": "content_replace", "content": content}

                        async def fake_call(context, stream=False, **kwargs):
                            self.assertTrue(responses, "最终回答后不得因工具缺口再次调用模型")
                            response = responses.pop(0)
                            if not stream:
                                return response

                            async def chunks():
                                if response.tool_calls:
                                    for index, tool in enumerate(response.tool_calls):
                                        tool.index = index
                                    parts = [types.SimpleNamespace(content=None, tool_calls=response.tool_calls)]
                                else:
                                    # 刻意拆开 final_answer 标签，覆盖真实增量输出。
                                    parts = [types.SimpleNamespace(content=piece, tool_calls=None)
                                             for piece in ("<final_", "answer>" + answer, "</final_answer>")]
                                for delta in parts:
                                    yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])
                            return chunks()

                        memory = [{"role": "user", "content": "请检索法条并读取附件"}]
                        with patch("agents.tool_loop.call", side_effect=fake_call) as model_call:
                            agent = ToolLoopAgent(
                                memory=memory, use_ocp=reviewed, output_review=Review() if reviewed else None,
                                execute_tool=lambda name, args: "ok", max_rounds=expected_calls,
                                mode="plan_and_solve" if planned else "default",
                                final_answer_source="tool_arg" if planned else "tagged_text",
                                tool_choice_policy=plan_and_solve_tool_choice_policy if planned else None,
                            )
                            events = [event async for event in agent.run(stream=stream)]
                        self.assertEqual(model_call.call_count, expected_calls)
                        self.assertFalse(responses)
                        visible = [event for event in events if event.get("type") in {"content", "content_replace"}]
                        self.assertEqual(visible, [{"type": "content_replace" if stream else "content", "content": answer}])
                        self.assertEqual(review_inputs, [answer] if reviewed else [])
                        self.assertFalse(any(msg.get("role") == "system" for msg in memory))
                        self.assertFalse(any(event.get("type") == "error" for event in events))


if __name__ == "__main__":
    unittest.main()
