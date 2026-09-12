"""
模块描述：设置页相关回归测试，覆盖权限边界、敏感信息脱敏与 provider 状态判断。
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient


TEST_SECRET = "x" * 32
LOCAL_ORIGIN = "http://localhost:5173"


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra"} or name.startswith("routes.") or name.startswith("services.") or name.startswith("infra."):
            sys.modules.pop(name, None)


class SettingsRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        os.environ["API_KEY"] = "env-llm-secret"
        os.environ["BASE_URL"] = "https://env-llm.example/v1"
        os.environ["LLM_MODEL"] = "env-llm-model"
        os.environ["DELI_APPID"] = "env-deli-appid"
        os.environ["DELI_SECRET"] = "env-deli-secret"
        os.environ["PKU_ACCESS_TOKEN"] = "test-pku"
        os.environ["QCC_ACCESS_TOKEN"] = "env-qcc-token"
        os.environ.pop("EMBEDDING_API_KEY", None)
        os.environ.pop("MEMORY_EMBEDDING_API_KEY", None)
        os.environ.pop("SILICONFLOW_API_KEY", None)

        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        for key in ("EMBEDDING_API_KEY", "MEMORY_EMBEDDING_API_KEY", "SILICONFLOW_API_KEY"):
            os.environ.pop(key, None)
        self.client = TestClient(self.agent.app, base_url="http://localhost")
        self._login_admin()

    def tearDown(self):
        self.client.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        purge_runtime_modules()

    def _login_admin(self):
        response = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(response.status_code, 200)

    def _create_user_client(self, username: str = "plain_user") -> TestClient:
        create = self.client.post(
            "/api/admin/accounts",
            json={"username": username, "password": "plain-password", "role": "user"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(create.status_code, 200)

        user_client = TestClient(self.agent.app, base_url="http://localhost")
        login = user_client.post(
            "/api/login",
            json={"username": username, "password": "plain-password"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(login.status_code, 200)
        return user_client

    def test_non_admin_cannot_access_admin_settings_endpoints(self):
        user_client = self._create_user_client()
        try:
            for path in ("/api/settings", "/api/providers/status", "/api/llm/models"):
                response = user_client.get(path)
                self.assertEqual(response.status_code, 403, path)
                self.assertEqual(response.json()["detail"], "Sudo access required")
        finally:
            user_client.close()

    def test_settings_response_redacts_secret_values(self):
        save_secret = self.client.post(
            "/api/settings/secret",
            json={"provider": "llm", "key": "api_key", "value": "saved-llm-secret"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(save_secret.status_code, 200)

        response = self.client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        llm = response.json()["providers"]["llm"]
        self.assertNotIn("api_key", llm)
        self.assertEqual(llm["base_url"], "https://env-llm.example/v1")
        self.assertEqual(llm["model"], "env-llm-model")

    def test_saved_settings_override_environment_fallback_in_response(self):
        save = self.client.post(
            "/api/settings",
            json={
                "providers": {
                    "llm": {
                        "enabled": True,
                        "base_url": "https://saved-llm.example/v1",
                        "model": "saved-llm-model",
                    }
                }
            },
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(save.status_code, 200)

        response = self.client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        llm = response.json()["providers"]["llm"]
        self.assertEqual(llm["base_url"], "https://saved-llm.example/v1")
        self.assertEqual(llm["model"], "saved-llm-model")

    def test_embedding_status_requires_api_key_before_reporting_ready(self):
        save = self.client.post(
            "/api/settings",
            json={
                "providers": {
                    "embedding": {
                        "enabled": True,
                        "base_url": "https://embedding.example/v1",
                        "model": "embedding-model",
                    }
                }
            },
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(save.status_code, 200)

        status_before = self.client.get("/api/providers/status")
        self.assertEqual(status_before.status_code, 200)
        embedding_before = next(item for item in status_before.json() if item["provider"] == "embedding")
        self.assertFalse(embedding_before["configured"])
        self.assertFalse(embedding_before["ok"])
        self.assertIn("api_key", embedding_before["message"])

        test_before = self.client.get("/api/providers/test/embedding")
        self.assertEqual(test_before.status_code, 400)
        self.assertIn("api_key", test_before.json()["detail"])

        save_secret = self.client.post(
            "/api/settings/secret",
            json={"provider": "embedding", "key": "api_key", "value": "saved-embedding-secret"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(save_secret.status_code, 200)

        status_after = self.client.get("/api/providers/status")
        self.assertEqual(status_after.status_code, 200)
        embedding_after = next(item for item in status_after.json() if item["provider"] == "embedding")
        self.assertTrue(embedding_after["configured"])
        self.assertTrue(embedding_after["ok"])
        self.assertEqual(embedding_after["message"], "已就绪")

        test_after = self.client.get("/api/providers/test/embedding")
        self.assertEqual(test_after.status_code, 200)
        self.assertTrue(test_after.json()["ok"])

    def test_secret_routes_reject_unknown_fields_and_provider_keys(self):
        extra = self.client.post(
            "/api/settings/secret",
            json={"provider": "llm", "key": "api_key", "value": "x", "unexpected": True},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(extra.status_code, 422)

        unknown_provider = self.client.post(
            "/api/settings/secret",
            json={"provider": "unknown", "key": "api_key", "value": "x"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(unknown_provider.status_code, 422)

        unsupported_key = self.client.post(
            "/api/settings/secret",
            json={"provider": "llm", "key": "not_a_real_secret", "value": "x"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(unsupported_key.status_code, 400)
        self.assertIn("不支持", unsupported_key.json()["detail"])

    def test_provider_path_is_an_enumerated_value(self):
        response = self.client.get("/api/providers/test/not-a-provider")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
