"""
模块描述：动态 prompt 与 Agent 构造测试，锁定 ReAct 降级和 Plan-and-Solve 新协议。
"""

import os
import asyncio
import unittest

from prompt_loader import build_system_prompt
from services.prompt_focus import current_focus, resolve_intent


class AgentDynamicPromptTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

    def test_react_prompt_falls_back_to_default(self):
        react_prompt = build_system_prompt(
            agent_mode="react",
            memory_context="<conversation_memory>统一记忆</conversation_memory>",
        )
        default_prompt = build_system_prompt(
            agent_mode="default",
            memory_context="<conversation_memory>统一记忆</conversation_memory>",
        )

        self.assertEqual(react_prompt, default_prompt)
        self.assertIn('name="default"', react_prompt)
        self.assertNotIn('name="react"', react_prompt)

    def test_plan_prompt_uses_control_plane_protocol(self):
        prompt = build_system_prompt(
            agent_mode="plan_and_solve",
            memory_context="<conversation_memory>统一记忆</conversation_memory>",
        )

        self.assertIn('name="plan_and_solve"', prompt)
        self.assertIn("submit_plan", prompt)
        self.assertIn("submit_final_answer", prompt)
        self.assertIn("<active_conversation_context>", prompt)
        self.assertIn("统一记忆", prompt)
        for forbidden in ("Action:", "Finish[", "# 可用工具", "# 完整计划", "```python"):
            self.assertNotIn(forbidden, prompt)

    def test_prompt_focus_routes_by_current_task(self):
        focus = current_focus("我要起诉一个上传的合同", [{"role": "user", "content": "合同.pdf"}])
        prompt = build_system_prompt(focus=focus)

        self.assertEqual(focus, ["general_gate", "legal_retrieval", "file_processing"])
        self.assertIn('name="general_gate"', prompt)
        self.assertIn('name="file_processing"', prompt)
        self.assertIn('name="legal_retrieval"', prompt)

        general_focus = current_focus("我们继续升级记忆系统架构", [])
        general_prompt = build_system_prompt(focus=general_focus)
        self.assertEqual(general_focus, ["general_gate"])
        self.assertIn('name="general_gate"', general_prompt)
        self.assertNotIn('name="file_processing"', general_prompt)
        self.assertNotIn('name="legal_retrieval"', general_prompt)

    def test_hybrid_router_uses_llm_for_low_confidence_and_fallbacks(self):
        import services.prompt_focus as prompt_focus

        original_classifier = prompt_focus.classify_intent_with_llm
        original_mode = os.environ.get("CONTEXT_ROUTER_MODE")
        try:
            os.environ["CONTEXT_ROUTER_MODE"] = "hybrid"

            async def fake_classifier(_content, _history):
                return {
                    "task_type": "legal_retrieval",
                    "confidence": 0.83,
                    "focus": ["general_gate", "legal_retrieval"],
                    "reasons": ["fake_llm"],
                    "source": "llm",
                    "requires_legal_evidence": True,
                    "requires_file_read": False,
                    "requires_workspace_listing": False,
                    "requires_memory_deep_search": False,
                }

            prompt_focus.classify_intent_with_llm = fake_classifier
            intent = asyncio.run(resolve_intent("帮我看看这个问题", []))
            self.assertEqual(intent["task_type"], "legal_retrieval")
            self.assertIn("legal_retrieval", intent["focus"])
            self.assertTrue(intent["requires_legal_evidence"])

            async def failing_classifier(_content, _history):
                raise RuntimeError("router unavailable")

            prompt_focus.classify_intent_with_llm = failing_classifier
            fallback = asyncio.run(resolve_intent("帮我看看这个问题", []))
            self.assertEqual(fallback["source"], "rules_fallback")
            self.assertEqual(fallback["focus"], ["general_gate"])
        finally:
            prompt_focus.classify_intent_with_llm = original_classifier
            if original_mode is None:
                os.environ.pop("CONTEXT_ROUTER_MODE", None)
            else:
                os.environ["CONTEXT_ROUTER_MODE"] = original_mode

    def test_llm_router_rejects_truthy_strings_and_unknown_task_types(self):
        from services.prompt_focus import _coerce_llm_intent

        intent = _coerce_llm_intent(
            '{"task_type":"invented_privileged_mode","confidence":"NaN",'
            '"focus":["general_gate"],"requires_file_read":"false",'
            '"requires_legal_evidence":true}'
        )

        self.assertIsNotNone(intent)
        self.assertEqual(intent["task_type"], "general")
        self.assertEqual(intent["confidence"], 0.65)
        self.assertFalse(intent["requires_file_read"])
        self.assertTrue(intent["requires_legal_evidence"])

    def test_greeting_history_does_not_create_tool_requirements(self):
        """欢迎语里的"合同/审查/分析"不得把纯文本问答判成必须读文件。

        历史回归：前端把欢迎语当历史下发，关键词打分扫到"合同审查/文件批注/案例分析"，
        于是每会话第一轮的纯文本法律问答都被判成 legal_file_review 且要求读取工作区文件；
        那一轮没有文件可读，缺口修复因此重写回答，最终把正确回答换成了拒绝模板。
        """
        from services.prompt_focus import route_intent_rules

        greeting = (
            "您好，我是 Lawver。\n"
            "- 案例分析：基于事实进行多维度法律分析（民事、行政、刑事）\n"
            "- 合同审查：支持PDF与Word文档的批注、修改及风险识别\n"
            "请问有什么法律问题需要我协助分析？"
        )
        routed = route_intent_rules(
            "有人偷窃外卖,可以追究作案者的哪些责任,考虑对方可能的抗辩手段",
            [{"role": "assistant", "content": greeting}],
        )

        self.assertFalse(routed["requires_file_read"])
        self.assertFalse(routed["requires_workspace_listing"])
        self.assertFalse(routed["requires_legal_evidence"])
        self.assertEqual(routed["task_type"], "general")

    def test_text_only_legal_question_does_not_require_files(self):
        from services.prompt_focus import route_intent_rules

        routed = route_intent_rules("申请劳动仲裁要准备哪些材料？", [])

        self.assertTrue(routed["requires_legal_evidence"])
        self.assertFalse(routed["requires_file_read"])
        self.assertFalse(routed["requires_workspace_listing"])

    def test_attachment_message_still_requires_file_read(self):
        from services.prompt_focus import route_intent_rules

        for content in ("帮我看看这份合同有什么风险", "这份.pdf 你读一下", "这张截图里的条款有问题吗"):
            routed = route_intent_rules(content, [])
            self.assertTrue(routed["requires_file_read"], content)
            self.assertTrue(routed["requires_workspace_listing"], content)

    def test_llm_router_preserves_semantic_tool_hints(self):
        """关键词未命中时，语义路由仍可识别附件指代与记忆追问。"""
        import services.prompt_focus as prompt_focus

        original_classifier = prompt_focus.classify_intent_with_llm
        original_mode = os.environ.get("CONTEXT_ROUTER_MODE")
        try:
            os.environ["CONTEXT_ROUTER_MODE"] = "hybrid"

            async def fake_classifier(_content, _history):
                return {
                    "task_type": "file_processing",
                    "confidence": 0.9,
                    "focus": ["general_gate", "file_processing"],
                    "reasons": ["fake_llm"],
                    "source": "llm",
                    "requires_legal_evidence": False,
                    "requires_file_read": True,
                    "requires_workspace_listing": True,
                    "requires_memory_deep_search": True,
                }

            prompt_focus.classify_intent_with_llm = fake_classifier
            intent = asyncio.run(resolve_intent("继续处理它，再找找上次说的内容", [{"role": "user", "content": "已上传劳动合同"}]))
        finally:
            prompt_focus.classify_intent_with_llm = original_classifier
            if original_mode is None:
                os.environ.pop("CONTEXT_ROUTER_MODE", None)
            else:
                os.environ["CONTEXT_ROUTER_MODE"] = original_mode

        self.assertTrue(intent["requires_file_read"])
        self.assertTrue(intent["requires_workspace_listing"])
        self.assertTrue(intent["requires_memory_deep_search"])

    def test_build_agent_react_falls_back_to_default_configuration(self):
        from services.agent_builder import build_agent
        from mcps import default_tools

        agent = build_agent("react", [{"role": "user", "content": "问题"}], "conv", "user/conv", use_ocp=False)

        self.assertEqual(agent.mode, "default")
        self.assertIs(agent.tools, default_tools)
        self.assertEqual(agent.final_answer_source, "tagged_text")
        self.assertIsNone(agent.tool_choice_policy)


if __name__ == "__main__":
    unittest.main()
