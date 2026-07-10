"""Focused regressions for bounded authentication, request bodies and private storage."""

import importlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

from pydantic import ValidationError
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response


TEST_SECRET = "s" * 32


def _mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class IsolatedBackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # These tests intentionally reload the memory package against a private
        # temporary database. Preserve collection-time modules so later tests
        # do not observe a split package/class identity after teardown.
        self.saved_memory_modules = {
            name: module
            for name, module in sys.modules.items()
            if name == "memory_system" or name.startswith("memory_system.")
        }
        self.old_env = {
            key: os.environ.get(key)
            for key in ("SECRET_KEY", "INITIAL_ADMIN_PASSWORD", "LAWVER_DATA_DIR", "LAWVER_MEMORY_DB")
        }
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        os.environ["LAWVER_MEMORY_DB"] = os.path.join(self.tmp, "memory_cache.sqlite3")
        self._purge_modules()

    def tearDown(self):
        self._purge_modules()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.modules.update(self.saved_memory_modules)
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _purge_modules():
        for name in list(sys.modules):
            if (
                name == "auth"
                or name == "services.settings_service"
                or name == "services.app_security"
                or name == "memory_system"
                or name.startswith("memory_system.")
            ):
                sys.modules.pop(name, None)


class AuthLockoutBudgetTests(IsolatedBackendTest):
    def test_unknown_accounts_do_not_persist_and_lockout_is_source_scoped(self):
        auth = importlib.import_module("auth")

        unknown_result = auth.authenticate_user("not-an-account", "bad-password", "198.51.100.20")
        self.assertEqual(unknown_result, (False, "用户名或密码错误"))
        self.assertFalse(os.path.exists(auth.LOCKOUT_FILE))

        for _ in range(auth.LOCKOUT_FAIL_LIMIT):
            result = auth.authenticate_user("admin", "bad-password", "198.51.100.21")
            self.assertEqual(result, (False, "用户名或密码错误"))

        locked_result = auth.authenticate_user("admin", "bootstrap-password", "198.51.100.21")
        other_source_result = auth.authenticate_user("admin", "bootstrap-password", "198.51.100.22")
        self.assertEqual(locked_result, unknown_result)
        self.assertEqual(other_source_result, (True, "登录成功"))

        with open(auth.LOCKOUT_FILE, "r", encoding="utf-8") as f:
            lockouts = json.load(f)
        self.assertEqual(len(lockouts), 1)
        self.assertTrue(all(key.startswith("v2:") and len(key) == 67 for key in lockouts))
        self.assertNotIn("admin", json.dumps(lockouts))

    def test_distributed_sources_share_progressive_account_bucket(self):
        auth = importlib.import_module("auth")

        # Stay below each client's hard limit while exhausting the aggregate
        # account budget across independent source identities.
        sources = ("198.51.100.31", "198.51.100.32", "198.51.100.33")
        for source in sources:
            for _ in range(2):
                result = auth.authenticate_user("admin", "bad-password", source)
                self.assertEqual(result, (False, "用户名或密码错误"))

        self.assertIsNotNone(auth.check_lockout("admin", "198.51.100.99"))
        self.assertEqual(
            auth.authenticate_user("admin", "bootstrap-password", "198.51.100.99"),
            (False, "用户名或密码错误"),
        )

        with open(auth.LOCKOUT_FILE, "r", encoding="utf-8") as f:
            lockouts = json.load(f)
        self.assertEqual(len(lockouts), 4)  # one account bucket + three client buckets
        self.assertEqual(
            max(record["fails"] for record in lockouts.values()),
            auth.ACCOUNT_LOCKOUT_PROGRESSIVE_START,
        )

    def test_lockout_cardinality_and_attacker_controlled_fields_are_bounded(self):
        auth = importlib.import_module("auth")
        accounts = auth.get_accounts_data()
        bootstrap_hash = accounts["admin"]["hash"]
        for index in range(12):
            accounts[f"user{index}"] = {"hash": bootstrap_hash, "role": "user"}
        auth._write_json(auth.ACCOUNT_FILE, accounts)

        auth.LOCKOUT_MAX_RECORDS = 4
        for index in range(12):
            auth.record_login_attempt(
                f"user{index}",
                False,
                "client-" + ("x" * 1_000),
                account_exists=True,
            )
        auth.record_login_attempt("z" * (auth.AUTH_USERNAME_MAX_LENGTH + 1), False, "client")

        with open(auth.LOCKOUT_FILE, "r", encoding="utf-8") as f:
            lockouts = json.load(f)
        self.assertLessEqual(len(lockouts), 4)
        self.assertTrue(all(len(key) == 67 for key in lockouts))
        self.assertTrue(all(set(record) == {"fails", "first_failed_at", "last_failed_at", "locked_until"} for record in lockouts.values()))


class PrivateStoragePermissionTests(IsolatedBackendTest):
    def test_existing_auth_and_secret_files_are_hardened_before_read(self):
        auth = importlib.import_module("auth")
        for _ in range(3):
            auth.authenticate_user("admin", "bad-password", "203.0.113.10")

        os.chmod(self.tmp, 0o777)
        os.chmod(auth.ACCOUNT_FILE, 0o666)
        os.chmod(auth.LOCKOUT_FILE, 0o666)
        auth._ensure_account_file()
        auth._read_lockouts()

        self.assertEqual(_mode(self.tmp), 0o700)
        self.assertEqual(_mode(auth.ACCOUNT_FILE), 0o600)
        self.assertEqual(_mode(auth.LOCKOUT_FILE), 0o600)
        self.assertEqual(_mode(auth.AUTH_STATE_LOCK_FILE), 0o600)

        settings = importlib.import_module("services.settings_service")
        settings.set_secret("llm", "api_key", "secret")
        os.chmod(settings.SECRETS_FILE, 0o666)
        self.assertEqual(settings.get_secret("llm", "api_key"), "secret")
        self.assertEqual(_mode(settings.SECRETS_FILE), 0o600)

    def test_memory_database_directory_database_and_sidecars_are_private(self):
        store = importlib.import_module("memory_system.service.store")
        store._ensure_memory_db()
        os.chmod(self.tmp, 0o777)
        os.chmod(os.environ["LAWVER_MEMORY_DB"], 0o666)

        conn = store._connect_memory_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR REPLACE INTO conversation_memory "
                "(scope, snapshot_json, revision, updated_at, last_accessed_at) VALUES (?, ?, ?, ?, ?)",
                ("scope", "{}", 0, "now", "now"),
            )
            conn.execute("COMMIT")
            store._harden_memory_storage()
            self.assertEqual(_mode(self.tmp), 0o700)
            for path in store._memory_db_paths():
                if os.path.exists(path):
                    self.assertEqual(_mode(path), 0o600)
        finally:
            conn.close()


class SchemaBudgetTests(unittest.TestCase):
    def test_request_enums_lengths_and_nesting_are_bounded(self):
        schemas = importlib.import_module("schemas")
        with self.assertRaises(ValidationError):
            schemas.ChatRequest(message="hello", agent_mode="unknown")
        with self.assertRaises(ValidationError):
            schemas.ChatRequest(message="hello", history=[{"role": "unknown", "content": "x"}])

        nested = {"value": "ok"}
        for _ in range(schemas.MAX_NESTING_DEPTH + 1):
            nested = {"next": nested}
        with self.assertRaises(ValidationError):
            schemas.ChatRequest(
                message="hello",
                history=[{"role": "user", "content": "x", "metadata": nested}],
            )

        with self.assertRaises(ValidationError):
            schemas.LoginRequest(username="u" * (schemas.MAX_USERNAME_CHARS + 1), password="password")

    def test_webdav_decoded_budget_is_checked_before_decode(self):
        schemas = importlib.import_module("schemas")
        old_decoded = schemas.WEBDAV_MAX_DECODED_BYTES
        old_encoded = schemas.WEBDAV_MAX_BASE64_CHARS
        schemas.WEBDAV_MAX_DECODED_BYTES = 2
        schemas.WEBDAV_MAX_BASE64_CHARS = 4
        try:
            with self.assertRaises(HTTPException) as raised:
                schemas.WebDavUploadRequest(
                    config={"url": "https://example.com", "username": "u", "password": "p"},
                    filename="backup.json",
                    data_b64="AAAA",
                )
            self.assertEqual(raised.exception.status_code, 413)
        finally:
            schemas.WEBDAV_MAX_DECODED_BYTES = old_decoded
            schemas.WEBDAV_MAX_BASE64_CHARS = old_encoded


class JsonBodyLimitTests(IsolatedBackendTest, unittest.IsolatedAsyncioTestCase):
    async def test_login_uses_a_small_pre_authentication_body_limit(self):
        app_security = importlib.import_module("services.app_security")

        async def receive():
            raise AssertionError("oversized Content-Length should be rejected before reading")

        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/login",
                "raw_path": b"/api/login",
                "query_string": b"",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(app_security.LOGIN_JSON_BODY_BYTES + 1).encode()),
                    (b"origin", b"http://localhost:5173"),
                ],
                "client": ("198.51.100.30", 1234),
                "server": ("localhost", 80),
            },
            receive,
        )

        response = await app_security.security_and_logging_middleware(
            request,
            lambda _request: (_ for _ in ()).throw(AssertionError("downstream should not run")),
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(json.loads(response.body)["code"], "json_body_too_large")

    async def test_chunked_json_without_content_length_is_rejected(self):
        app_security = importlib.import_module("services.app_security")
        app_security.MAX_JSON_BODY_BYTES = 8
        messages = iter(
            [
                {"type": "http.request", "body": b'{"data":', "more_body": True},
                {"type": "http.request", "body": b'"too-large"}', "more_body": False},
            ]
        )

        async def receive():
            return next(messages)

        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/test",
                "raw_path": b"/api/test",
                "query_string": b"",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"origin", b"http://localhost:5173"),
                ],
                "client": ("198.51.100.30", 1234),
                "server": ("localhost", 80),
            },
            receive,
        )
        downstream_called = False

        async def call_next(_request):
            nonlocal downstream_called
            downstream_called = True
            return Response("ok")

        response = await app_security.security_and_logging_middleware(request, call_next)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(downstream_called)
        self.assertEqual(json.loads(response.body)["code"], "json_body_too_large")


if __name__ == "__main__":
    unittest.main()
