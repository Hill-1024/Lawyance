import os
import unittest

from prompt_loader import build_system_memory, build_system_prompt


class PromptLoaderTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("LAWVER_PROMPT_INCLUDE_EXAMPLES", None)

    def test_builds_default_prompt_with_focus_and_memory_context(self):
        prompt = build_system_prompt(
            agent_mode="default",
            focus=["legal_retrieval"],
            memory_context="<conversation_memory>强解耦</conversation_memory>",
        )

        self.assertIn("Lawver", prompt)
        self.assertIn("<hard_constraints", prompt)
        self.assertIn('name="default"', prompt)
        self.assertIn('name="legal_retrieval"', prompt)
        self.assertIn("<active_conversation_context>", prompt)
        self.assertIn("强解耦", prompt)

    def test_unknown_mode_falls_back_to_default(self):
        prompt = build_system_prompt(agent_mode="unknown")

        self.assertIn('name="default"', prompt)

    def test_history_summary_uses_task_specific_prompt_only(self):
        messages = build_system_memory(task="history_summary")
        prompt = messages[0]["content"]

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("对话摘要器", prompt)
        self.assertNotIn("<hard_constraints", prompt)

    def test_examples_are_optional(self):
        prompt_without_examples = build_system_prompt()
        self.assertNotIn("<example", prompt_without_examples)

        os.environ["LAWVER_PROMPT_INCLUDE_EXAMPLES"] = "1"
        prompt_with_examples = build_system_prompt()
        self.assertIn("<example", prompt_with_examples)


if __name__ == "__main__":
    unittest.main()
