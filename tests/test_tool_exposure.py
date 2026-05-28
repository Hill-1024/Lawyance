"""
模块描述：工具 exposure 稳定性测试，锁定默认模式与 Plan-and-Solve 工具隔离。
"""

import hashlib
import json
import unittest

from tools import registry


class ToolExposureTests(unittest.TestCase):
    def test_default_tools_do_not_include_control_plane(self):
        names = set(registry.names("agent"))

        self.assertNotIn("submit_plan", names)
        self.assertNotIn("submit_final_answer", names)

    def test_plan_and_solve_tools_include_business_and_control_plane_tools(self):
        default_names = set(registry.names("agent"))
        plan_names = set(registry.names("plan_and_solve"))

        self.assertTrue(default_names.issubset(plan_names))
        self.assertIn("submit_plan", plan_names)
        self.assertIn("submit_final_answer", plan_names)

    def test_court_tools_are_read_only_and_no_control_plane(self):
        names = set(registry.names("court"))

        self.assertIn("search_article", names)
        self.assertIn("match_legal_case", names)
        self.assertIn("web_search", names)
        self.assertIn("retrieve_conversation_memory", names)
        self.assertIn("pdf_text_reader", names)
        self.assertIn("word_reader", names)
        self.assertIn("txt_md_reader", names)
        self.assertIn("list_workspace_files", names)
        self.assertNotIn("pdf_commit_by_sentence", names)
        self.assertNotIn("word_writer", names)
        self.assertNotIn("txt_md_writer", names)
        self.assertNotIn("submit_plan", names)
        self.assertNotIn("submit_final_answer", names)

    def test_tool_schema_bytes_are_stable_per_exposure(self):
        for exposure in ("agent", "plan_and_solve", "court"):
            first = json.dumps(registry.schemas(exposure), ensure_ascii=False, sort_keys=False)
            second = json.dumps(registry.schemas(exposure), ensure_ascii=False, sort_keys=False)
            self.assertEqual(
                hashlib.sha256(first.encode()).hexdigest(),
                hashlib.sha256(second.encode()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
