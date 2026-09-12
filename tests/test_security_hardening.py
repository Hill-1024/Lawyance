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
from starlette.requests import Request


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
TEST_SECRET = "x" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra"} or name.startswith("routes.") or name.startswith("services.") or name.startswith("infra."):
            sys.modules.pop(name, None)


class SecurityBootstrapTests(unittest.TestCase):
    def test_missing_secret_key_fails_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.pop("SECRET_KEY", None)
            env.pop("INITIAL_ADMIN_PASSWORD", None)
            env["LAWVER_DATA_DIR"] = tmp
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
            env["LAWVER_DATA_DIR"] = tmp
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
            env["LAWVER_DATA_DIR"] = tmp
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
            old_env = {key: os.environ.get(key) for key in ("SECRET_KEY", "INITIAL_ADMIN_PASSWORD", "LAWVER_DATA_DIR")}
            os.environ["SECRET_KEY"] = TEST_SECRET
            os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
            os.environ["LAWVER_DATA_DIR"] = tmp
            sys.modules.pop("auth", None)
            try:
                auth = importlib.import_module("auth")
                auth_store = importlib.import_module("infra.auth_store")
                captured_errors = []

                # Lockout records are only created for real accounts. Reuse the
                # bootstrap hash so this concurrency test stays focused on the
                # atomic lockout update rather than password hashing setup.
                accounts = auth.get_accounts_data()
                bootstrap_hash = accounts["admin"]["hash"]
                for index in range(8):
                    auth_store.insert_user_record(
                        {
                            "username": f"user{index}",
                            "password_hash": bootstrap_hash,
                            "role": "user",
                            "auth_version": 0,
                            "owner": None,
                            "max_online": None,
                            "max_users": None,
                            "user_max_online": None,
                        }
                    )

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

                # Each real account has an aggregate account bucket and a
                # username/client bucket.
                self.assertEqual(len(lockouts), 16)
                self.assertTrue(all(key.startswith("v2:") and len(key) == 67 for key in lockouts))
                for index in range(8):
                    username = f"user{index}"
                    client_record = lockouts[auth._client_lockout_key(username, "unknown")]
                    account_record = lockouts[auth._account_lockout_key(username)]
                    self.assertEqual(client_record["fails"], auth.LOCKOUT_FAIL_LIMIT)
                    self.assertGreater(client_record["locked_until"], 0)
                    self.assertGreaterEqual(account_record["fails"], auth.LOCKOUT_FAIL_LIMIT)
                    self.assertLessEqual(
                        account_record["fails"],
                        auth.ACCOUNT_LOCKOUT_PROGRESSIVE_START,
                    )
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
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("PKU_ACCESS_TOKEN", "test-pku")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")

        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.client = TestClient(self.agent.app, base_url="http://localhost")

    def tearDown(self):
        self.client.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        purge_runtime_modules()

    def test_login_cookie_is_http_only_strict_and_dev_non_secure(self):
        response = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": "http://localhost:5173"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.json())
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertNotIn("; secure", cookie)

    def test_native_login_returns_bearer_token_and_accepts_authorization(self):
        response = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={
                "origin": "https://localhost:443",
                "x-lawver-client": "capacitor",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("token", data)
        self.assertEqual(data["username"], "admin")
        self.assertEqual(data["role"], "sudo")

        stateless_client = TestClient(self.agent.app, base_url="http://localhost")
        try:
            verify = stateless_client.get(
                "/api/verify_auth",
                headers={
                    "authorization": f"Bearer {data['token']}",
                    "x-lawver-client": "capacitor",
                },
            )
        finally:
            stateless_client.close()

        self.assertEqual(verify.status_code, 200)
        self.assertEqual(verify.json()["username"], "admin")

    def test_deleted_account_token_is_rejected_immediately(self):
        admin_login = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": "http://localhost:5173"},
        )
        self.assertEqual(admin_login.status_code, 200)

        create_user = self.client.post(
            "/api/admin/accounts",
            json={"username": "revoked_user", "password": "secret-password", "role": "user"},
            headers={"origin": "http://localhost:5173"},
        )
        self.assertEqual(create_user.status_code, 200)

        user_client = TestClient(self.agent.app, base_url="http://localhost")
        try:
            user_login = user_client.post(
                "/api/login",
                json={"username": "revoked_user", "password": "secret-password"},
                headers={
                    "origin": "https://localhost:443",
                    "x-lawver-client": "capacitor",
                },
            )
            self.assertEqual(user_login.status_code, 200)
            token = user_login.json()["token"]

            delete_user = self.client.delete(
                "/api/admin/accounts/revoked_user",
                headers={"origin": "http://localhost:5173"},
            )
            self.assertEqual(delete_user.status_code, 200)

            verify = user_client.get(
                "/api/verify_auth",
                headers={"authorization": f"Bearer {token}", "x-lawver-client": "capacitor"},
            )
        finally:
            user_client.close()

        self.assertEqual(verify.status_code, 401)

    def test_password_reset_invalidates_older_bearer_token(self):
        admin_login = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": "http://localhost:5173"},
        )
        self.assertEqual(admin_login.status_code, 200)

        create_user = self.client.post(
            "/api/admin/accounts",
            json={"username": "reset_user", "password": "old-password", "role": "user"},
            headers={"origin": "http://localhost:5173"},
        )
        self.assertEqual(create_user.status_code, 200)

        user_client = TestClient(self.agent.app, base_url="http://localhost")
        try:
            user_login = user_client.post(
                "/api/login",
                json={"username": "reset_user", "password": "old-password"},
                headers={
                    "origin": "https://localhost:443",
                    "x-lawver-client": "capacitor",
                },
            )
            self.assertEqual(user_login.status_code, 200)
            token = user_login.json()["token"]

            reset_password = self.client.post(
                "/api/admin/accounts",
                json={"username": "reset_user", "password": "new-password", "role": "user"},
                headers={"origin": "http://localhost:5173"},
            )
            self.assertEqual(reset_password.status_code, 200)

            verify_old_token = user_client.get(
                "/api/verify_auth",
                headers={"authorization": f"Bearer {token}", "x-lawver-client": "capacitor"},
            )
            new_login = user_client.post(
                "/api/login",
                json={"username": "reset_user", "password": "new-password"},
                headers={
                    "origin": "https://localhost:443",
                    "x-lawver-client": "capacitor",
                },
            )
        finally:
            user_client.close()

        self.assertEqual(verify_old_token.status_code, 401)
        self.assertEqual(new_login.status_code, 200)

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

    def test_admin_can_clear_usage_logs(self):
        login = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": "http://localhost:5173"},
        )
        self.assertEqual(login.status_code, 200)

        log_path = os.path.join(self.tmp, "usage.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("2026-05-26 10:00:00,000 | INFO | 127.0.0.1 | admin | GET | /api/example | 200\n")
        with open(f"{log_path}.1", "w", encoding="utf-8") as f:
            f.write("rotated log\n")

        response = self.client.delete("/api/admin/logs", headers={"origin": "http://localhost:5173"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        with open(log_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "")
        self.assertFalse(os.path.exists(f"{log_path}.1"))

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

    def test_forwarded_ip_headers_are_only_trusted_from_configured_proxies(self):
        app_security = importlib.import_module("services.app_security")

        def make_request(client_host: str, headers: list[tuple[bytes, bytes]]) -> Request:
            return Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/verify_auth",
                    "headers": headers,
                    "client": (client_host, 1234),
                    "scheme": "http",
                    "server": ("localhost", 80),
                }
            )

        old_trusted_proxies = os.environ.pop("LAWVER_TRUSTED_PROXY_CIDRS", None)
        try:
            private_direct = make_request("10.0.0.8", [(b"x-forwarded-for", b"203.0.113.9")])
            self.assertEqual(app_security.client_ip_for_request(private_direct), "10.0.0.8")

            loopback_proxy = make_request("127.0.0.1", [(b"x-forwarded-for", b"203.0.113.9")])
            self.assertEqual(app_security.client_ip_for_request(loopback_proxy), "203.0.113.9")

            malformed_forwarded = make_request("127.0.0.1", [(b"x-forwarded-for", b"not-an-ip")])
            self.assertEqual(app_security.client_ip_for_request(malformed_forwarded), "127.0.0.1")

            os.environ["LAWVER_TRUSTED_PROXY_CIDRS"] = "10.0.0.0/8"
            configured_proxy = make_request("10.0.0.8", [(b"cf-connecting-ip", b"198.51.100.22")])
            self.assertEqual(app_security.client_ip_for_request(configured_proxy), "198.51.100.22")
        finally:
            if old_trusted_proxies is None:
                os.environ.pop("LAWVER_TRUSTED_PROXY_CIDRS", None)
            else:
                os.environ["LAWVER_TRUSTED_PROXY_CIDRS"] = old_trusted_proxies


if __name__ == "__main__":
    unittest.main()
