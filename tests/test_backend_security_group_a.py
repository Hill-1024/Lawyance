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
    """节流策略的回归：状态现在存在 Postgres（Redis 做快路径），不再是本地 JSON 文件。"""

    def _rows(self):
        throttle = importlib.import_module("infra.throttle")
        from sqlalchemy import select

        with throttle.transaction() as session:
            return [
                {
                    "scope": row.scope,
                    "key": row.key,
                    "fails": row.fails,
                    "locked": row.locked_until,
                }
                for row in session.scalars(select(throttle.LoginThrottle)).all()
            ]

    def test_unknown_accounts_do_not_persist_and_lockout_is_source_scoped(self):
        auth = importlib.import_module("auth")
        throttle = importlib.import_module("infra.throttle")

        unknown_result = auth.authenticate_user("not-an-account", "bad-password", "198.51.100.20")
        self.assertEqual(unknown_result, (False, "用户名或密码错误"))
        # 不存在的账号绝不落桶，否则攻击者能用任意用户名刷出一堆记录。
        self.assertEqual(throttle.snapshot(), [])

        for _ in range(auth.LOCKOUT_FAIL_LIMIT):
            result = auth.authenticate_user("admin", "bad-password", "198.51.100.21")
            self.assertEqual(result, (False, "用户名或密码错误"))

        locked_result = auth.authenticate_user("admin", "bootstrap-password", "198.51.100.21")
        other_source_result = auth.authenticate_user("admin", "bootstrap-password", "198.51.100.22")
        # 锁只作用于这个来源；换个来源仍能正常登录。
        # 锁定期间**密码正确**的本人会看到锁定提示（否则他会以为密码被改了）；
        # 密码错误的尝试仍回统一文案，见下一个测试的断言。
        self.assertEqual(locked_result, (False, auth.check_lockout("admin", "198.51.100.21")))
        self.assertIn("已被锁定", locked_result[1])
        self.assertEqual(other_source_result, (True, "登录成功"))

        raw = str([(row["scope"], row["key"]) for row in self._rows()])
        # 键必须是摘要——原始用户名与来源不得出现在存储里。
        self.assertNotIn("admin", raw)
        self.assertNotIn("198.51.100.21", raw)

    def test_distributed_sources_share_progressive_account_bucket(self):
        auth = importlib.import_module("auth")

        # Stay below each client's hard limit while exhausting the aggregate
        # account budget across independent source identities.
        sources = ("198.51.100.31", "198.51.100.32", "198.51.100.33")
        for source in sources:
            for _ in range(2):
                result = auth.authenticate_user("admin", "bad-password", source)
                self.assertEqual(result, (False, "用户名或密码错误"))

        # 聚合桶在跨来源第 6 次失败时开始退避锁定。
        self.assertIsNotNone(auth.check_lockout("admin", "198.51.100.99"))
        # 密码正确 → 提示已被锁定（不泄露给只是猜密码的人）。
        self.assertIn(
            "已被锁定",
            auth.authenticate_user("admin", "bootstrap-password", "198.51.100.99")[1],
        )
        # 密码错误 → 仍是统一文案。
        self.assertEqual(
            auth.authenticate_user("admin", "bad-password", "198.51.100.99"),
            (False, "用户名或密码错误"),
        )

        rows = self._rows()
        self.assertEqual(len(rows), 4)  # one account bucket + three client buckets
        self.assertEqual(max(row["fails"] for row in rows), auth.ACCOUNT_LOCKOUT_PROGRESSIVE_START)

    def test_lockout_cardinality_and_attacker_controlled_fields_are_bounded(self):
        auth = importlib.import_module("auth")
        throttle = importlib.import_module("infra.throttle")
        throttle.LOCKOUT_MAX_RECORDS = 4
        self.addCleanup(setattr, throttle, "LOCKOUT_MAX_RECORDS", 4096)

        for index in range(12):
            auth.record_login_attempt(
                f"user{index}",
                False,
                "client-" + ("x" * 1_000),
                account_exists=True,
            )
        auth.record_login_attempt("z" * (auth.AUTH_USERNAME_MAX_LENGTH + 1), False, "client")

        rows = self._rows()
        # 每个用户名会写「来源 + 账号」两个桶，24 条被压回上限内。
        self.assertLessEqual(len(rows), 4 + 1)
        self.assertTrue(all(len(row["key"]) == 64 for row in rows))
        raw = str([(row["scope"], row["key"]) for row in rows])
        self.assertNotIn("client-", raw)
        self.assertNotIn("user1", raw)


class LockoutUnlockTests(IsolatedBackendTest):
    """管理员解锁：用户误操作被锁两小时后，线上不该只能干等。"""

    def test_admin_unlock_restores_login(self):
        auth = importlib.import_module("auth")
        throttle = importlib.import_module("infra.throttle")

        for _ in range(auth.LOCKOUT_FAIL_LIMIT):
            auth.authenticate_user("admin", "bad-password", "198.51.100.40")
        # 锁上之后连正确密码也进不去，但本人能看到「已被锁定」而不是被误导成密码错
        blocked = auth.authenticate_user("admin", "bootstrap-password", "198.51.100.40")
        self.assertFalse(blocked[0])
        self.assertIn("已被锁定", blocked[1])
        self.assertGreater(throttle.locked_seconds("admin", "198.51.100.40"), 0)

        cleared = throttle.unlock("admin")
        self.assertGreaterEqual(cleared, 1)
        self.assertEqual(throttle.locked_seconds("admin", "198.51.100.40"), 0)
        self.assertEqual(
            auth.authenticate_user("admin", "bootstrap-password", "198.51.100.40"),
            (True, "登录成功"),
        )

    def test_unlock_does_not_touch_other_accounts(self):
        auth = importlib.import_module("auth")
        throttle = importlib.import_module("infra.throttle")

        for _ in range(auth.LOCKOUT_FAIL_LIMIT):
            auth.authenticate_user("admin", "bad-password", "198.51.100.41")

        # 另一个账号也被锁上；解锁 admin 不能把它一起带走。
        for _ in range(3):
            throttle.record_failure("someone-else", "198.51.100.42", bucket=throttle.SCOPE_CLIENT)
        self.assertGreater(throttle.locked_map(["admin"])["admin"], 0)
        self.assertGreater(throttle.locked_map(["someone-else"])["someone-else"], 0)

        throttle.unlock("admin")
        self.assertEqual(throttle.locked_map(["admin"])["admin"], 0)
        self.assertGreater(throttle.locked_map(["someone-else"])["someone-else"], 0)


@unittest.skipIf(os.name == "nt", "POSIX 权限位在 Windows 上不可用：os.chmod 只能切换只读位")
class PrivateStoragePermissionTests(IsolatedBackendTest):
    def test_existing_auth_and_secret_files_are_hardened_before_read(self):
        # 账号在云端库、登录节流也在云端库，本机已经没有 auth.sqlite3 与
        # lockout.json；这条用例只剩「数据目录本身必须收紧」。
        auth = importlib.import_module("auth")
        os.chmod(self.tmp, 0o777)
        auth._ensure_account_file()

        self.assertEqual(_mode(self.tmp), 0o700)
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


class SchemaBudgetTests(unittest.IsolatedAsyncioTestCase):
    """两个 async 测试需要事件循环：继承 TestCase 时它们只会被当成未 await 的协程，从未真正执行。"""
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
