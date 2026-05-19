"""
模块描述：动态 prompt loader 测试，覆盖 profile 片段组合、焦点注入和可选示例加载。
"""

import os
import hashlib
import unittest

from prompt_loader import build_system_memory, build_system_prompt


class PromptLoaderTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("LAWYANCE_PROMPT_INCLUDE_EXAMPLES", None)

    def test_builds_default_prompt_with_focus_and_memory_context(self):
        prompt = build_system_prompt(
            agent_mode="default",
            focus=["legal_retrieval"],
            memory_context="<conversation_memory>强解耦</conversation_memory>",
        )

        self.assertIn("Lawyance", prompt)
        self.assertIn("<hard_constraints", prompt)
        self.assertIn('name="default"', prompt)
        self.assertIn('name="legal_retrieval"', prompt)
        self.assertIn("<active_conversation_context>", prompt)
        self.assertIn("强解耦", prompt)
        self.assertNotIn("模块描述", prompt)

    def test_unknown_mode_falls_back_to_default(self):
        prompt = build_system_prompt(agent_mode="unknown")

        self.assertIn('name="default"', prompt)

    def test_history_summary_uses_task_specific_prompt_only(self):
        messages = build_system_memory(task="history_summary")
        prompt = messages[0]["content"]

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("对话摘要器", prompt)
        self.assertNotIn("<hard_constraints", prompt)
        self.assertNotIn("模块描述", prompt)

    def test_examples_are_optional(self):
        prompt_without_examples = build_system_prompt()
        self.assertNotIn("<example", prompt_without_examples)

        os.environ["LAWYANCE_PROMPT_INCLUDE_EXAMPLES"] = "1"
        prompt_with_examples = build_system_prompt()
        self.assertIn("<example", prompt_with_examples)

    def test_build_system_memory_returns_three_systems_when_memory_present(self):
        messages = build_system_memory(
            agent_mode="default",
            focus=["legal_retrieval", "file_processing", "general_gate"],
            memory_context="<conversation_memory>事实A</conversation_memory>",
        )

        self.assertEqual(len(messages), 3)
        self.assertTrue(all(message["role"] == "system" for message in messages))
        self.assertIn("<hard_constraints", messages[0]["content"])
        self.assertIn('name="default"', messages[0]["content"])
        self.assertNotIn("<constraint_recap", messages[0]["content"])
        self.assertNotIn("<active_conversation_context>", messages[0]["content"])

        self.assertIn("<active_conversation_context>", messages[1]["content"])
        self.assertIn("事实A", messages[1]["content"])
        self.assertNotIn("<constraint_recap", messages[1]["content"])

        self.assertIn("<constraint_recap", messages[-1]["content"])
        self.assertNotIn("<hard_constraints", messages[-1]["content"])

    def test_build_system_memory_without_memory_returns_two_systems(self):
        messages = build_system_memory(agent_mode="default", memory_context="   \n  ")

        self.assertEqual(len(messages), 2)
        self.assertTrue(all(message["role"] == "system" for message in messages))
        self.assertIn("<hard_constraints", messages[0]["content"])
        self.assertIn("<constraint_recap", messages[-1]["content"])
        self.assertNotIn("<active_conversation_context>", messages[0]["content"])
        self.assertNotIn("<active_conversation_context>", messages[-1]["content"])

    def test_static_prefix_and_recap_are_byte_stable_across_memory_changes(self):
        focus = ["legal_retrieval", "file_processing", "general_gate"]
        first = build_system_memory(
            agent_mode="default",
            focus=focus,
            memory_context="<conversation_memory>事实A</conversation_memory>",
        )
        second = build_system_memory(
            agent_mode="default",
            focus=focus,
            memory_context="<conversation_memory>事实B</conversation_memory>",
        )

        self.assertEqual(
            hashlib.sha256(first[0]["content"].encode()).hexdigest(),
            hashlib.sha256(second[0]["content"].encode()).hexdigest(),
        )
        self.assertEqual(
            hashlib.sha256(first[-1]["content"].encode()).hexdigest(),
            hashlib.sha256(second[-1]["content"].encode()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
