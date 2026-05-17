"""
模块描述：安全加固回归测试，覆盖启动密钥、初始管理员、CORS/CSRF、Cookie 和锁定策略。
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
TEST_SECRET = "x" * 32


class SecurityBootstrapTests(unittest.TestCase):
    def test_missing_secret_key_fails_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.pop("SECRET_KEY", None)
            env.pop("INITIAL_ADMIN_PASSWORD", None)
            env["LAWYANCE_DATA_DIR"] = tmp
            env["PYTHONPATH"] = REPO_ROOT
            result = subprocess.run(
                [sys.executable, "-c", "import auth"],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY", result.stderr + result.stdout)

    def test_missing_initial_admin_password_fails_when_no_account_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["SECRET_KEY"] = TEST_SECRET
            env.pop("INITIAL_ADMIN_PASSWORD", None)
            env["LAWYANCE_DATA_DIR"] = tmp
            env["PYTHONPATH"] = REPO_ROOT
            result = subprocess.run(
                [sys.executable, "-c", "import auth"],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("INITIAL_ADMIN_PASSWORD", result.stderr + result.stdout)

    def test_existing_insecure_default_admin_hash_fails_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            account_path = os.path.join(tmp, "account.json")
            with open(account_path, "w", encoding="utf-8") as f:
                f.write(
                    '{"admin": {"hash": "cf632ecdd2c9b4e67cd76de4db6b785d$'
                    '12b8bd1ec5414d7a46abf6b92a4bc0319ca7b9662bba71bc9776dcbefc4c0177", "role": "admin"}}'
                )
            env = os.environ.copy()
            env["SECRET_KEY"] = TEST_SECRET
            env["LAWYANCE_DATA_DIR"] = tmp
            env["PYTHONPATH"] = REPO_ROOT
            result = subprocess.run(
                [sys.executable, "-c", "import auth"],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Insecure default admin account", result.stderr + result.stdout)


class AuthStateConcurrencyTests(unittest.TestCase):
    def test_parallel_failed_logins_preserve_lockout_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = {key: os.environ.get(key) for key in ("SECRET_KEY", "INITIAL_ADMIN_PASSWORD", "LAWYANCE_DATA_DIR")}
            os.environ["SECRET_KEY"] = TEST_SECRET
            os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
            os.environ["LAWYANCE_DATA_DIR"] = tmp
            sys.modules.pop("auth", None)
            try:
                auth = importlib.import_module("auth")
                captured_errors = []

                def capture_print(*args, **_kwargs):
                    captured_errors.append(" ".join(str(arg) for arg in args))

                auth.print = capture_print

                def fail_login(index: int):
                    return auth.authenticate_user(f"user{index % 8}", "bad-password")

                with ThreadPoolExecutor(max_workers=32) as executor:
                    results = list(executor.map(fail_login, range(400)))

                self.assertEqual(len(results), 400)
                self.assertTrue(all(not success for success, _ in results))
                self.assertEqual(captured_errors, [])

                with open(os.path.join(tmp, "lockout.json"), "r", encoding="utf-8") as f:
                    lockouts = json.load(f)

                self.assertEqual(set(lockouts), {f"user{i}" for i in range(8)})
                self.assertTrue(all(item["fails"] == 3 for item in lockouts.values()))
                self.assertTrue(all(item["locked_until"] > 0 for item in lockouts.values()))
            finally:
                sys.modules.pop("auth", None)
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


class ApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWYANCE_DATA_DIR"] = self.tmp
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("PKU_ACCESS_TOKEN", "test-pku")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

        sys.modules.pop("agent", None)
        sys.modules.pop("auth", None)
        self.agent = importlib.import_module("agent")
        self.client = TestClient(self.agent.app, base_url="http://localhost")

    def tearDown(self):
        self.client.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        sys.modules.pop("agent", None)
        sys.modules.pop("auth", None)

    def test_login_cookie_is_http_only_strict_and_dev_non_secure(self):
        response = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": "http://localhost:5173"},
        )

        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertNotIn("; secure", cookie)

    def test_cross_site_unsafe_api_request_is_rejected(self):
        response = self.client.post("/api/logout", headers={"origin": "https://evil.example"})

        self.assertEqual(response.status_code, 403)
        self.assertIn("Forbidden origin", response.text)

    def test_cookie_authenticated_unsafe_api_requires_origin_or_referer(self):
        login = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": "http://localhost:5173"},
        )
        self.assertEqual(login.status_code, 200)

        response = self.client.post("/api/logout")

        self.assertEqual(response.status_code, 403)
        self.assertIn("Missing origin", response.text)

        allowed = self.client.post("/api/logout", headers={"origin": "http://localhost:5173"})
        self.assertEqual(allowed.status_code, 200)

    def test_cors_allows_configured_origin_but_not_arbitrary_origin(self):
        allowed = self.client.options(
            "/api/verify_auth",
            headers={
                "origin": "https://law.mutsumi.moe",
                "access-control-request-method": "GET",
            },
        )
        denied = self.client.options(
            "/api/verify_auth",
            headers={
                "origin": "https://evil.example",
                "access-control-request-method": "GET",
            },
        )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "https://law.mutsumi.moe")
        self.assertNotEqual(denied.headers.get("access-control-allow-origin"), "https://evil.example")


if __name__ == "__main__":
    unittest.main()
