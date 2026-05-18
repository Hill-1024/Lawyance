"""
模块描述：工具 registry 兼容性测试，锁定 LLM 可见工具顺序与 exposure 分类。
"""

import os
import unittest

os.environ.setdefault("DELI_APPID", "test-deli-app")
os.environ.setdefault("DELI_SECRET", "test-deli-secret")
os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

import mcps
from tools import registry


EXPECTED_AGENT_TOOL_NAMES = [
    "match_legal_case",
    "get_article",
    "search_article",
    "get_linked_content",
    "pdf_text_reader",
    "pdf_commit_by_sentence",
    "word_reader",
    "word_writer",
    "list_workspace_files",
    "retrieve_conversation_memory",
    "inspect_conversation_memory",
    "update_conversation_memory",
    "get_company_profile",
    "get_company_registration_info",
    "get_contact_info",
    "get_external_investments",
    "get_key_personnel",
    "get_listing_info",
    "get_shareholder_info",
]


class ToolSchemaCompatibilityTests(unittest.TestCase):
    def test_agent_tool_names_and_order_are_stable(self):
        self.assertEqual(
            [tool["function"]["name"] for tool in mcps.tools],
            EXPECTED_AGENT_TOOL_NAMES,
        )
        self.assertEqual(registry.names("agent"), EXPECTED_AGENT_TOOL_NAMES)

    def test_internal_memory_tools_dispatch_but_are_not_agent_visible(self):
        self.assertEqual(
            registry.names("internal"),
            ["sync_conversation_memory", "remember_conversation_turn", "clear_conversation_memory"],
        )
        agent_names = set(registry.names("agent"))
        self.assertFalse(agent_names & set(registry.names("internal")))
        result = mcps.use_tools("clear_conversation_memory", {}, conv_id="tester/conv")
        self.assertNotIn("工具不存在", str(result))

    def test_ocp_reviewer_tools_are_law_source_subset(self):
        self.assertEqual(
            registry.names("ocp_reviewer"),
            ["get_article", "search_article", "get_linked_content"],
        )
        self.assertTrue(set(registry.names("ocp_reviewer")).issubset(set(registry.names("agent"))))

    def test_unknown_tool_error_semantics_are_stable(self):
        self.assertIn("工具不存在", mcps.use_tools("missing_tool", {}, conv_id="tester/conv"))


if __name__ == "__main__":
    unittest.main()
