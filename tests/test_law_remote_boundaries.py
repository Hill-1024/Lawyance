"""客户包完全没有 RAG 时，完整应用生命周期与已注册工具仍能工作。"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class RemoteLawApplicationBoundaryTests(unittest.TestCase):
    def test_app_lifespan_and_registered_tools_work_without_rag_or_law_cache(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            # 实际复制客户运行文件；不把源码仓库或 RAG 放进子进程的搜索路径。
            for name in ("backend", "tools"):
                shutil.copytree(REPO_ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for name in ("agent.py", "package.json"):
                shutil.copyfile(REPO_ROOT / name, root / name)
            self.assertFalse((root / "RAG").exists())
            env = {
                **os.environ,
                "SECRET_KEY": "r" * 32,
                "INITIAL_ADMIN_PASSWORD": "isolated-test-password",
                "LAWVER_DATA_DIR": str(root / "runtime"),
                "LAWVER_DATABASE_URL": "",
                "LAWVER_REDIS_URL": "",
                "LAWVER_WORKBENCH_TESTING": "1",
                "LAWVER_WORKBENCH_READ_ONLY": "1",
                "LAWVER_RELEASE_SYNC_ON_STARTUP": "0",
                "LAWVER_LAW_SOURCE": "remote",
                "LAWVER_LAW_SERVICE_URL": "http://127.0.0.1:8084",
                "LAWVER_LAW_SERVICE_KEY": "lvk_isolated-test",
                "LAWVER_LAW_SERVICE_TIMEOUT": "10",
                "PKU_LAW_SOURCE": "remote",  # 新显式开关必须覆盖旧第三方配置。
                "MEMORY_EMBEDDING_ENABLED": "0",
                "API_KEY": "isolated-test-key",
                "BASE_URL": "http://127.0.0.1:1/v1",
                "LLM_MODEL": "isolated-test-model",
            }
            script = textwrap.dedent(r'''
                import importlib.abc
                import json
                from pathlib import Path
                import sys
                from unittest import mock

                root = Path.cwd()
                sys.path[:0] = [str(root / "backend"), str(root)]

                class NoRag(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path=None, target=None):
                        if fullname == "RAG" or fullname.startswith("RAG."):
                            raise AssertionError("customer application attempted a RAG import")
                        return None

                sys.meta_path.insert(0, NoRag())
                from fastapi.testclient import TestClient
                from mcp import law_service_client

                sentinel = "REMOTE_LAW_TEXT_MUST_NOT_BE_PERSISTED_01"
                article = {"law_name": "TestLaw", "article_number": "1", "content": sentinel, "url": "https://example.test/source"}

                class Response:
                    status_code = 200
                    def __init__(self, payload):
                        self.body = json.dumps(payload).encode()
                    def iter_content(self, chunk_size):
                        yield self.body
                    def close(self):
                        pass

                with mock.patch.object(law_service_client.requests, "post") as post:
                    import agent
                    import mcps
                    with TestClient(agent.app) as client:
                        assert client.get("/api/health").status_code == 200
                        assert agent.app.state.law_cache_status["mode"] == "remote"
                        post.assert_not_called()  # 启动校验配置，但不依赖远程在线。
                        post.side_effect = [
                            Response({"success": True, "data": article}),
                            Response({"success": True, "data": [article]}),
                            Response({"success": True, "text": sentinel}),
                        ]
                        calls = [
                            ("get_article", {"title": "TestLaw", "number": "1"}),
                            ("search_article", {"query": "TestLaw"}),
                            ("get_linked_content", {"message": "TestLaw 1"}),
                        ]
                        for name, args in calls:
                            result = mcps.use_tools(name, args)
                            assert json.loads(result)["success"], (name, result)
                            assert sentinel in result
                        assert post.call_count == 3
                assert not any(name == "RAG" or name.startswith("RAG.") for name in sys.modules)
                assert not (root / "RAG").exists()
                for path in root.rglob("*"):
                    if path.is_file():
                        assert path.name not in {"law.db", "manifest.json"}, path
                        assert sentinel.encode() not in path.read_bytes(), path
                print("REMOTE_APP_WITHOUT_RAG_OK")
            ''')
            # -I 忽略外部 PYTHONPATH 和用户 site，确保没有借用当前源码中的 RAG。
            completed = subprocess.run(
                [sys.executable, "-I", "-c", script], cwd=root, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("REMOTE_APP_WITHOUT_RAG_OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
