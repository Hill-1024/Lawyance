"""
模块描述：动态 prompt 与 Agent 构造测试，锁定 ReAct 降级和 Plan-and-Solve 新协议。
"""

import os
import unittest

from prompt_loader import build_system_prompt
from services.prompt_focus import current_focus


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

    def test_prompt_focus_is_constant_and_prompt_sections_self_gate(self):
        focus = current_focus("我要起诉一个上传的合同", [{"role": "user", "content": "合同.pdf"}])
        prompt = build_system_prompt(focus=focus)

        self.assertEqual(focus, ["general_gate", "file_processing", "legal_retrieval"])
        self.assertIn('name="general_gate"', prompt)
        self.assertIn('name="file_processing"', prompt)
        self.assertIn('name="legal_retrieval"', prompt)
        self.assertIn("视本节为非激活指引", prompt)

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
