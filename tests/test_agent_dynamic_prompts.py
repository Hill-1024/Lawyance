"""
模块描述：动态 prompt 注入测试，验证各 Agent 范式按阶段接收系统记忆与约束。
"""

import os
import copy
import types
import unittest

from prompt_loader import build_system_prompt


async def _content_stream(text: str):
    delta = types.SimpleNamespace(reasoning_content=None, thought_signature=None, content=text)
    yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


class AgentDynamicPromptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

    def test_prompt_loader_injects_react_and_plan_modes_with_memory_context(self):
        react_prompt = build_system_prompt(
            agent_mode="react",
            memory_context="<conversation_memory>统一记忆</conversation_memory>",
        )
        plan_prompt = build_system_prompt(
            agent_mode="plan_and_solve",
            memory_context="<conversation_memory>统一记忆</conversation_memory>",
        )

        self.assertIn('name="react"', react_prompt)
        self.assertIn("范式规则由本动态 prompt 注入", react_prompt)
        self.assertIn("Action: Finish[<final_answer>", react_prompt)
        self.assertIn("<active_conversation_context>", react_prompt)
        self.assertIn("统一记忆", react_prompt)

        self.assertIn('name="plan_and_solve"', plan_prompt)
        self.assertIn("规划阶段规则", plan_prompt)
        self.assertIn("执行阶段规则", plan_prompt)
        self.assertIn("<active_conversation_context>", plan_prompt)
        self.assertIn("统一记忆", plan_prompt)

    async def test_react_agent_uses_injected_memory_and_minimal_task_payload(self):
        import agents.react as react_module
        from agents.react import ReActAgent

        captured = []
        original_call = react_module.call

        async def fake_call(context, stream=False, include_tools=True):
            captured.append({
                "context": copy.deepcopy(context),
                "stream": stream,
                "include_tools": include_tools,
            })
            return _content_stream("Thought: 已完成\nAction: Finish[<final_answer>完成</final_answer>]")

        try:
            react_module.call = fake_call
            memory = [
                {"role": "system", "content": "DYNAMIC_SYSTEM"},
                {"role": "assistant", "content": "前情"},
            ]
            agent = ReActAgent(
                "search_article: 检索法条",
                lambda name, args: "观察",
                memory=memory,
            )
            events = [event async for event in agent.run("劳动合同到期怎么办")]
        finally:
            react_module.call = original_call

        self.assertEqual(captured[0]["context"][0]["content"], "DYNAMIC_SYSTEM")
        self.assertFalse(captured[0]["include_tools"])
        user_prompt = captured[0]["context"][-1]["content"]
        self.assertIn("# 可用工具", user_prompt)
        self.assertIn("# 当前问题", user_prompt)
        self.assertIn("# 已执行的 ReAct 步骤", user_prompt)
        self.assertIn("search_article: 检索法条", user_prompt)
        self.assertEqual(user_prompt.count("劳动合同到期怎么办"), 1)
        self.assertNotIn("Few Shot Example", user_prompt)
        self.assertNotIn("你必须遵守 system prompt", user_prompt)
        self.assertTrue(any(event.get("type") == "content" and event.get("content") == "完成" for event in events))

    async def test_plan_and_solve_agent_uses_injected_memory_for_each_phase(self):
        import agents.plan_and_solve as plan_module
        from agents.plan_and_solve import PlanAndSolveAgent

        captured = []
        original_call = plan_module.call
        responses = [
            '```python\n["检索解除劳动合同规则"]\n```',
            "Action: search_article[解除劳动合同 经济补偿]",
            "已检索到解除劳动合同经济补偿规则。",
            "<final_answer>完成</final_answer>",
        ]

        async def fake_call(context, stream=False, include_tools=True):
            captured.append({
                "context": copy.deepcopy(context),
                "stream": stream,
                "include_tools": include_tools,
            })
            return _content_stream(responses[len(captured) - 1])

        try:
            plan_module.call = fake_call
            memory = [{"role": "system", "content": "DYNAMIC_PLAN_SYSTEM"}]
            agent = PlanAndSolveAgent(
                tools_description="search_article: 检索法条",
                execute_tool=lambda name, args: "《劳动合同法》相关内容",
                memory=memory,
            )
            events = [event async for event in agent.run("被公司解除劳动合同怎么办")]
        finally:
            plan_module.call = original_call

        self.assertEqual(len(captured), 4)
        self.assertTrue(all(call["context"][0]["content"] == "DYNAMIC_PLAN_SYSTEM" for call in captured))
        self.assertTrue(all(call["include_tools"] is False for call in captured))

        planner_prompt = captured[0]["context"][-1]["content"]
        self.assertIn("# 当前问题", planner_prompt)
        self.assertNotIn("你的任务是将用户提出的法律问题", planner_prompt)
        self.assertNotIn("示例:", planner_prompt)

        executor_prompt = captured[1]["context"][-1]["content"]
        self.assertIn("# 可用工具", executor_prompt)
        self.assertIn("# 完整计划", executor_prompt)
        self.assertIn("# 当前步骤", executor_prompt)
        self.assertNotIn("核心约束", executor_prompt)

        observation_prompt = captured[2]["context"][-1]["content"]
        self.assertIn("# 工具执行结果", observation_prompt)

        final_prompt = captured[3]["context"][-1]["content"]
        self.assertIn("# 执行过程", final_prompt)
        self.assertNotIn("要求：", final_prompt)
        self.assertTrue(any(event.get("type") == "content_replace" and event.get("content") == "完成" for event in events))


if __name__ == "__main__":
    unittest.main()
