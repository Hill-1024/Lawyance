"""客户包没有 RAG 和向量引擎时，远程模式的应用与工具仍能工作。"""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class RemoteLawApplicationBoundaryTests(unittest.TestCase):
    def test_app_lifespan_and_registered_tools_work_without_local_law_engines(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp) / "customer"
            # 使用真实客户导出器，避免全量复制 backend 暗中携带向量检索引擎。
            spec = importlib.util.spec_from_file_location(
                "boundary_package_customer", REPO_ROOT / "scripts/package-customer.py"
            )
            packager = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(packager)
            context = Path(tmp) / "customer-build-context"
            packager.build_context(REPO_ROOT, context)
            manifest = packager.export_directory(context, root, no_git_context=True)
            self.assertFalse((root / "RAG").exists())
            self.assertFalse((root / "backend/vector_store").exists())
            self.assertFalse((root / "law_service").exists())
            self.assertFalse((root / ".env").exists())
            self.assertTrue(manifest["files"])
            env = {
                **{
                    name: value for name, value in os.environ.items()
                    if name.upper() in {
                        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"
                    }
                },
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
                # remote 必须优先于主线新增的两个向量开关。
                "LAWVER_VECTOR_DB_ENABLED": "1",
                "LAWVER_VECTOR_RETRIEVAL_ENABLED": "1",
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

                attempted_local_imports = []

                class NoLocalLawEngine(importlib.abc.MetaPathFinder):
                    def find_spec(self, fullname, path=None, target=None):
                        if any(
                            fullname == prefix or fullname.startswith(prefix + ".")
                            for prefix in ("RAG", "vector_store", "backend.vector_store")
                        ):
                            attempted_local_imports.append(fullname)
                            raise AssertionError("customer attempted a local law engine import: " + fullname)
                        return None

                sys.meta_path.insert(0, NoLocalLawEngine())
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
                # 即使生产代码捕获导入异常并回退，尝试导入本地引擎也必须失败。
                assert not attempted_local_imports, attempted_local_imports
                assert not any(
                    name == prefix or name.startswith(prefix + ".")
                    for name in sys.modules
                    for prefix in ("RAG", "vector_store", "backend.vector_store")
                )
                assert not (root / "RAG").exists()
                assert not (root / "backend/vector_store").exists()
                for path in root.rglob("*"):
                    if path.is_file():
                        assert path.name not in {"law.db", "manifest.json"}, path
                        assert sentinel.encode() not in path.read_bytes(), path
                print("REMOTE_APP_WITHOUT_LOCAL_LAW_ENGINES_OK")
            ''')
            # -I 忽略外部 PYTHONPATH 和用户 site，确保没有借用当前源码中的 RAG。
            completed = subprocess.run(
                [sys.executable, "-I", "-B", "-c", script], cwd=root, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("REMOTE_APP_WITHOUT_LOCAL_LAW_ENGINES_OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
