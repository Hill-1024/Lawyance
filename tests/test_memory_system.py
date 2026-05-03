import json
import unittest
from uuid import uuid4

from mcp.memory_client import (
    clear_conversation_memory,
    remember_conversation_turn,
    retrieve_conversation_memory,
    sync_conversation_memory,
)


class ConversationMemorySystemTests(unittest.TestCase):
    def setUp(self):
        self.scope = f"tester/{uuid4()}"

    def tearDown(self):
        clear_conversation_memory(self.scope)

    def test_sync_observes_history_and_retrieves_fuzzy_context(self):
        payload = json.loads(
            sync_conversation_memory(
                self.scope,
                snapshot={},
                messages=[
                    {
                        "role": "user",
                        "content": "严格遵守我们的项目结构设计哲学：强解耦与高复用。记忆只需要做到对话级，暂时不用做到用户级。",
                    }
                ],
            )
        )

        self.assertEqual(payload["status"], "success")
        self.assertGreaterEqual(len(payload["memory"]["facts"]), 1)

        retrieved = json.loads(retrieve_conversation_memory(self.scope, "用户级记忆和架构边界怎么处理", limit=5))
        self.assertEqual(retrieved["status"], "success")
        self.assertIn("对话级", retrieved["context"])
        self.assertIn("强解耦", retrieved["context"])

    def test_semantic_retrieval_without_literal_keywords(self):
        json.loads(
            sync_conversation_memory(
                self.scope,
                snapshot={},
                messages=[
                    {
                        "role": "user",
                        "content": "严格遵守我们的项目结构设计哲学：强解耦与高复用。不要跨模块直接访问，统一走 mcps 请求转发黑箱模式。",
                    }
                ],
            )
        )

        retrieved = json.loads(retrieve_conversation_memory(self.scope, "隔离各组件时是不是只能通过总线调度", limit=5))
        self.assertIn("强解耦", retrieved["context"])
        self.assertTrue(any("semantic" in item.get("routes", []) for item in retrieved["items"]))

    def test_semantic_fact_retrieval_without_payment_keyword(self):
        json.loads(
            sync_conversation_memory(
                self.scope,
                snapshot={},
                messages=[
                    {"role": "user", "content": "记住：案件事实是甲公司已经付款。"},
                ],
            )
        )

        retrieved = json.loads(retrieve_conversation_memory(self.scope, "款项是否已经结清", limit=5))
        self.assertIn("甲公司已经付款", retrieved["context"])
        self.assertTrue(any("semantic" in item.get("routes", []) for item in retrieved["items"]))

    def test_entity_route_retrieves_company_specific_memory(self):
        json.loads(
            sync_conversation_memory(
                self.scope,
                snapshot={},
                messages=[
                    {"role": "user", "content": "记住：乙公司尚未交付标的物。"},
                ],
            )
        )

        retrieved = json.loads(retrieve_conversation_memory(self.scope, "乙公司后续履行风险怎么处理", limit=5))
        self.assertIn("乙公司尚未交付标的物", retrieved["context"])
        self.assertTrue(any("entity" in item.get("routes", []) for item in retrieved["items"]))

    def test_remember_turn_returns_client_persistable_snapshot(self):
        payload = json.loads(
            remember_conversation_turn(
                self.scope,
                "我希望后续先讨论技术方案，再开始实现。",
                "明白，后续会先确认方案再动手。",
            )
        )

        memory = payload["memory"]
        self.assertEqual(memory["scope"]["type"], "conversation")
        self.assertGreaterEqual(len(memory["events"]), 2)
        self.assertTrue(any("先讨论技术方案" in fact["text"] for fact in memory["facts"]))

    def test_clear_removes_active_server_cache(self):
        json.loads(remember_conversation_turn(self.scope, "记住这个对话级约束。", "已记录。"))
        clear_payload = json.loads(clear_conversation_memory(self.scope))
        self.assertEqual(clear_payload["status"], "success")

        retrieved = json.loads(retrieve_conversation_memory(self.scope, "对话级约束", limit=5))
        self.assertEqual(retrieved["context"], "")
        self.assertEqual(retrieved["items"], [])

    def test_sync_rebuilds_from_current_messages_after_undo(self):
        original = json.loads(
            sync_conversation_memory(
                self.scope,
                snapshot={},
                messages=[
                    {"role": "user", "content": "记住：案件事实是甲公司已经付款。"},
                    {"role": "assistant", "content": "已记录。"},
                ],
            )
        )
        self.assertIn("甲公司已经付款", json.dumps(original["memory"], ensure_ascii=False))

        rebuilt = json.loads(
            sync_conversation_memory(
                self.scope,
                snapshot=original["memory"],
                messages=[],
            )
        )
        self.assertNotIn("甲公司已经付款", json.dumps(rebuilt["memory"], ensure_ascii=False))

        retrieved = json.loads(retrieve_conversation_memory(self.scope, "甲公司付款", limit=5))
        self.assertEqual(retrieved["context"], "")
        self.assertEqual(retrieved["items"], [])


if __name__ == "__main__":
    unittest.main()
