"""
模块描述：工具 exposure 稳定性测试，锁定默认模式与 Plan-and-Solve 工具隔离。
"""

import hashlib
import json
import unittest

import mcps
from tools import registry
from services.agent_builder import build_tool_executor


class ToolExposureTests(unittest.TestCase):
    def test_default_tools_do_not_include_control_plane(self):
        names = set(registry.names("agent"))

        self.assertIn("ask_user", names)
        self.assertNotIn("submit_plan", names)
        self.assertNotIn("submit_final_answer", names)

    def test_plan_and_solve_tools_include_business_and_control_plane_tools(self):
        default_names = set(registry.names("agent"))
        plan_names = set(registry.names("plan_and_solve"))

        self.assertTrue(default_names.issubset(plan_names))
        self.assertIn("ask_user", plan_names)
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
        self.assertNotIn("ask_user", names)
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

    def test_dispatch_rejects_hidden_tools_for_agent_and_court_capabilities(self):
        default_executor = build_tool_executor("tester/conv", "agent")
        clear_result = default_executor("clear_conversation_memory", {})
        final_result = default_executor("submit_final_answer", {"answer": "bypass"})
        court_result = registry.dispatch(
            "submit_final_answer",
            {"answer": "bypass"},
            "tester/court",
            capability="court",
        )

        for result in (clear_result, final_result, court_result):
            self.assertEqual(result["error"], "tool_not_authorized")
        self.assertEqual(clear_result["capability"], "agent")
        self.assertEqual(court_result["capability"], "court")

    def test_dispatch_without_capability_fails_closed(self):
        result = registry.dispatch(
            "get_article",
            {"title": "民法典", "number": "第一条"},
            "tester/conv",
        )

        self.assertEqual(result["error"], "tool_not_authorized")
        self.assertEqual(result["capability"], "missing")

    def test_ocp_capability_cannot_forge_internal_or_writer_tools(self):
        for tool_name, arguments in (
            ("clear_conversation_memory", {}),
            ("txt_md_writer", {"file_path": "result.md", "content": "blocked"}),
        ):
            result = mcps.use_tools(
                tool_name,
                arguments,
                conv_id="tester/conv",
                capability="ocp_reviewer",
            )
            self.assertEqual(result["error"], "tool_not_authorized")
            self.assertEqual(result["capability"], "ocp_reviewer")

    def test_plan_capability_can_execute_control_plane_but_not_internal_clear(self):
        final_result = registry.dispatch(
            "submit_final_answer",
            {"answer": "ok"},
            "tester/conv",
            capability="plan_and_solve",
        )
        clear_result = registry.dispatch(
            "clear_conversation_memory",
            {},
            "tester/conv",
            capability="plan_and_solve",
        )

        self.assertEqual(final_result, {"acknowledged": True})
        self.assertEqual(clear_result["error"], "tool_not_authorized")


if __name__ == "__main__":
    unittest.main()
