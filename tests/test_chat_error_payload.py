"""
模块描述：聊天错误 payload 兼容性测试，锁定前端读取的 memory_snapshot 字段名。
"""

import importlib
import os
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

from memory_system import MemoryRevisionConflict


TEST_SECRET = "y" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra"} or name.startswith("routes.") or name.startswith("services.") or name.startswith("infra."):
            sys.modules.pop(name, None)


class ChatErrorPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp.name
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("PKU_ACCESS_TOKEN", "test-pku")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")
        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.chat_pipeline = importlib.import_module("services.chat_pipeline")

    def tearDown(self):
        self.tmp.cleanup()
        purge_runtime_modules()

    def test_memory_revision_conflict_payload_keeps_frontend_field_names(self):
        snapshot = {"revision": 7, "facts": [{"id": "fact_1", "text": "旧事实"}]}

        def raise_conflict(*_args, **_kwargs):
            raise MemoryRevisionConflict(expected_revision=3, actual_revision=7, snapshot=snapshot)

        original_sync = self.chat_pipeline.sync_memory_cache
        try:
            self.chat_pipeline.sync_memory_cache = raise_conflict
            with TestClient(self.agent.app, base_url="http://localhost") as client:
                login = client.post(
                    "/api/login",
                    json={"username": "admin", "password": "bootstrap-password"},
                    headers={"origin": "http://localhost:5173"},
                )
                self.assertEqual(login.status_code, 200)
                response = client.post(
                    "/api/chat",
                    json={
                        "message": "测试",
                        "history": [],
                        "conversation_id": "conv",
                        "stream": False,
                    },
                    headers={"origin": "http://localhost:5173"},
                )
        finally:
            self.chat_pipeline.sync_memory_cache = original_sync

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            {
                "error": "memory_revision_conflict",
                "expected_revision": 3,
                "actual_revision": 7,
                "memory_snapshot": snapshot,
            },
        )

    def test_streaming_chat_terminates_with_done_marker(self):
        class FakeAgent:
            async def run(self, content=None, stream=True):
                yield {"type": "content", "content": "ok"}

        def fake_build_agent(*_args, **_kwargs):
            return FakeAgent()

        original_build_agent = self.chat_pipeline.build_agent
        original_sync = self.chat_pipeline.sync_memory_cache
        original_retrieve = self.chat_pipeline.retrieve_memory_context
        original_remember = self.chat_pipeline.remember_memory_turn
        try:
            self.chat_pipeline.build_agent = fake_build_agent
            self.chat_pipeline.sync_memory_cache = lambda *args, **kwargs: {}
            self.chat_pipeline.retrieve_memory_context = lambda *args, **kwargs: ("", {})
            self.chat_pipeline.remember_memory_turn = lambda *args, **kwargs: {}

            with TestClient(self.agent.app, base_url="http://localhost") as client:
                login = client.post(
                    "/api/login",
                    json={"username": "admin", "password": "bootstrap-password"},
                    headers={"origin": "http://localhost:5173"},
                )
                self.assertEqual(login.status_code, 200)
                response = client.post(
                    "/api/chat",
                    json={
                        "message": "测试",
                        "history": [],
                        "conversation_id": "conv",
                        "stream": True,
                    },
                    headers={"origin": "http://localhost:5173"},
                )
        finally:
            self.chat_pipeline.build_agent = original_build_agent
            self.chat_pipeline.sync_memory_cache = original_sync
            self.chat_pipeline.retrieve_memory_context = original_retrieve
            self.chat_pipeline.remember_memory_turn = original_remember

        self.assertEqual(response.status_code, 200)
        self.assertIn('data: {"type": "stream_start", "seq": 0, "stream_id": "turn_', response.text)
        self.assertIn('data: {"type": "content", "content": "ok", "seq": 1}', response.text)
        self.assertIn('data: {"type": "done"', response.text)
        self.assertTrue(response.text.rstrip().endswith("data: [DONE]"))


if __name__ == "__main__":
    unittest.main()
