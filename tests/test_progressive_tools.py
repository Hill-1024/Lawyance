"""
模块描述：工具渐进式披露（清单 + select_tools 按需加载 schema）单元测试。
"""

from __future__ import annotations

import importlib
import json
import os
import unittest


class ProgressiveToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools_mod = importlib.import_module("tools")
        cls.progressive = importlib.import_module("tools.progressive")
        cls.registry = importlib.import_module("tools.registry").registry
        cls.tool_loop = importlib.import_module("agents.tool_loop")

    def test_initial_round_only_exposes_always_on_tools(self):
        agent_tools = self.registry.schemas("agent")
        self.assertGreater(len(agent_tools), 5)
        self.assertIn(self.progressive.SELECT_TOOLS_NAME, self.registry.names("agent"))

        os.environ["LAWVER_PROGRESSIVE_TOOLS"] = "1"
        try:
            agent = self.tool_loop.ToolLoopAgent(tools=agent_tools, mode="default", use_ocp=False)
            state = agent._new_state()
            round_tools = agent._tools_for_round(state)
        finally:
            os.environ.pop("LAWVER_PROGRESSIVE_TOOLS", None)

        names = {
            (tool.get("function") or {}).get("name")
            for tool in (round_tools or [])
        }
        self.assertIn("select_tools", names)
        self.assertIn("ask_user", names)
        self.assertNotIn("search_article", names)
        self.assertLess(len(names), len(agent_tools))

    def test_select_tools_loads_business_schema_next_round(self):
        agent_tools = self.registry.schemas("agent")
        os.environ["LAWVER_PROGRESSIVE_TOOLS"] = "1"
        try:
            agent = self.tool_loop.ToolLoopAgent(tools=agent_tools, mode="default", use_ocp=False)
            state = agent._new_state()
            payload = json.loads(agent._activate_tools({"tools": ["search_article", "get_article"]}, state))
            round_tools = agent._tools_for_round(state)
        finally:
            os.environ.pop("LAWVER_PROGRESSIVE_TOOLS", None)

        self.assertTrue(payload["success"])
        self.assertIn("search_article", payload["loaded_tools"])
        names = {
            (tool.get("function") or {}).get("name")
            for tool in (round_tools or [])
        }
        self.assertIn("search_article", names)
        self.assertIn("get_article", names)
        self.assertIn("select_tools", names)

    def test_catalog_injected_ephemerally(self):
        agent_tools = self.registry.schemas("agent")
        os.environ["LAWVER_PROGRESSIVE_TOOLS"] = "1"
        try:
            agent = self.tool_loop.ToolLoopAgent(tools=agent_tools, mode="default", use_ocp=False)
            state = agent._new_state()
            mem = [
                {"role": "system", "content": "base"},
                {"role": "user", "content": "hello"},
            ]
            contextual = agent._context_for_round(mem, state)
        finally:
            os.environ.pop("LAWVER_PROGRESSIVE_TOOLS", None)

        self.assertEqual(len(mem), 2)
        self.assertEqual(len(contextual), 3)
        self.assertEqual(contextual[1]["role"], "system")
        self.assertIn("渐进式披露", contextual[1]["content"])
        self.assertIn("search_article", contextual[1]["content"])

    def test_progressive_can_be_disabled(self):
        agent_tools = self.registry.schemas("agent")
        os.environ["LAWVER_PROGRESSIVE_TOOLS"] = "0"
        try:
            agent = self.tool_loop.ToolLoopAgent(tools=agent_tools, mode="default", use_ocp=False)
            state = agent._new_state()
            round_tools = agent._tools_for_round(state)
        finally:
            os.environ.pop("LAWVER_PROGRESSIVE_TOOLS", None)

        self.assertFalse(agent.progressive_tools)
        self.assertEqual(len(round_tools or []), len(agent_tools))


if __name__ == "__main__":
    unittest.main()
