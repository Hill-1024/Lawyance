"""
模块描述：工具 schema 序列化稳定性回归测试，防止 prefix cache 因 schema 字节变化失效。
"""

import hashlib
import json
import unittest

import mcps  # noqa: F401 触发工具注册与 agent schema 暴露路径
from tools import registry


class ToolSchemaStabilityTest(unittest.TestCase):
    def test_agent_schemas_serialize_identically_on_repeat(self):
        first = json.dumps(registry.schemas("agent"), ensure_ascii=False, sort_keys=False)
        second = json.dumps(registry.schemas("agent"), ensure_ascii=False, sort_keys=False)
        self.assertEqual(
            hashlib.sha256(first.encode()).hexdigest(),
            hashlib.sha256(second.encode()).hexdigest(),
            "tools schema 序列化不稳定，会破坏 LLM prefix cache",
        )

    def test_agent_schemas_have_stable_order(self):
        names_first = [schema["function"]["name"] for schema in registry.schemas("agent")]
        names_second = [schema["function"]["name"] for schema in registry.schemas("agent")]
        self.assertEqual(names_first, names_second)


if __name__ == "__main__":
    unittest.main()
