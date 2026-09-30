"""E2E 实机测试报告（TEMP/e2e-live-test-report-2026-09-30.md）修复项的回归测试。

只覆盖能在进程内确证的语义：停用账号的登录与会话签发、锁定提示只对密码正确者可见、
自助改密、工作台门禁与测试模式派生库的一致性。路由状态码与前端行为由实机复验覆盖。
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

TEST_SECRET = "s" * 32


class IsolatedAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_env = {
            key: os.environ.get(key)
            for key in (
                "SECRET_KEY",
                "INITIAL_ADMIN_PASSWORD",
                "LAWVER_DATA_DIR",
                "LAWVER_DATABASE_URL",
                "LAWVER_WORKBENCH_TESTING",
                "LAWVER_WORKBENCH_USERS",
            )
        }
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        self._purge_modules()

    def tearDown(self):
        self._purge_modules()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _purge_modules():
        for name in list(sys.modules):
            if name == "auth" or name.startswith("auth.") or name in {
                "services.app_security",
                "infra.database",
                "infra.account_store",
                "workbench.api",
            }:
                sys.modules.pop(name, None)


class SuspendedAccountTests(IsolatedAuthTest):
    """CARD-02：停用必须真的停用——不能靠「只撤一次存量会话」实现。"""

    def _auth(self):
        auth = importlib.import_module("auth")
        auth.ensure_auth_store_ready()
        auth.upsert_account(
            "admin", "alice", "alice-password", role="user", plan="pro", billing_cycle="monthly"
        )
        return auth

    def test_suspended_account_cannot_log_in_and_session_is_not_issued(self):
        auth = self._auth()
        self.assertEqual(auth.authenticate_user("alice", "alice-password"), (True, "登录成功"))

        ok, message = auth.set_account_status("admin", "alice", "suspended")
        self.assertTrue(ok, message)

        # 正确密码也必须被挡住，并且给本人的提示要说明原因，不能伪装成「密码错误」。
        allowed, reason = auth.authenticate_user("alice", "alice-password")
        self.assertFalse(allowed)
        self.assertIn("已停用", reason)

        # 会话签发链路是第二个入口，同样不能放行。
        issued, session_message, sid, _evicted = auth.create_session("alice")
        self.assertFalse(issued)
        self.assertIsNone(sid)
        self.assertIn("已停用", session_message)

        # 重新启用后恢复登录。
        self.assertTrue(auth.set_account_status("admin", "alice", "active")[0])
        self.assertEqual(auth.authenticate_user("alice", "alice-password"), (True, "登录成功"))

    def test_wrong_password_on_suspended_account_still_generic(self):
        """停用状态不向不知道密码的人泄露。"""
        auth = self._auth()
        auth.set_account_status("admin", "alice", "suspended")
        allowed, reason = auth.authenticate_user("alice", "not-the-password")
        self.assertFalse(allowed)
        self.assertEqual(reason, "用户名或密码错误")


class ChangePasswordTests(IsolatedAuthTest):
    """CARD-07：自助改密需要当前密码，改完保留当前设备、其他设备下线。"""

    def _auth(self):
        auth = importlib.import_module("auth")
        auth.ensure_auth_store_ready()
        auth.upsert_account("admin", "bob", "bob-password", role="user")
        return auth

    def test_requires_current_password_and_rejects_same_password(self):
        auth = self._auth()
        self.assertIn("当前密码", auth.change_password("bob", "wrong", "new-password-1")[1])
        self.assertIn("不能与当前密码相同", auth.change_password("bob", "bob-password", "bob-password")[1])
        self.assertIn("不能小于", auth.change_password("bob", "bob-password", "short")[1])
        # 失败路径不该改掉密码
        self.assertEqual(auth.authenticate_user("bob", "bob-password"), (True, "登录成功"))

    def test_keeps_current_session_and_revokes_others(self):
        auth = self._auth()
        first = auth.create_session("bob")[2]
        second = auth.create_session("bob")[2]
        self.assertEqual("bob", auth.verify_token(first))
        self.assertEqual("bob", auth.verify_token(second))

        ok, message, revoked = auth.change_password(
            "bob", "bob-password", "bob-password-2", keep_sid=second
        )
        self.assertTrue(ok, message)
        self.assertGreaterEqual(revoked, 1)
        # 当前设备继续可用，其他设备失效
        self.assertEqual("bob", auth.verify_token(second))
        self.assertIsNone(auth.verify_token(first))
        # 旧密码失效、新密码可用
        self.assertFalse(auth.authenticate_user("bob", "bob-password")[0])
        self.assertEqual(auth.authenticate_user("bob", "bob-password-2"), (True, "登录成功"))

    def test_change_password_clears_login_lockout(self):
        auth = self._auth()
        for _ in range(auth.LOCKOUT_FAIL_LIMIT):
            auth.authenticate_user("bob", "wrong-password")
        self.assertIsNotNone(auth.check_lockout("bob", "unknown"))
        self.assertTrue(auth.change_password("bob", "bob-password", "bob-password-3")[0])
        self.assertIsNone(auth.check_lockout("bob", "unknown"))


class WorkbenchGateTests(IsolatedAuthTest):
    """CARD-04：门禁与 infra.database 的「库是否可用」必须同一判据。"""

    def _enabled(self):
        api = importlib.import_module("workbench.api")
        return api.enabled

    def test_testing_mode_without_explicit_url_enables_workbench(self):
        os.environ["LAWVER_WORKBENCH_TESTING"] = "1"
        os.environ.pop("LAWVER_DATABASE_URL", None)
        os.environ.pop("LAWVER_WORKBENCH_USERS", None)
        enabled = self._enabled()
        self.assertTrue(enabled("anyone"))

    def test_explicit_user_list_still_scopes_access(self):
        os.environ["LAWVER_WORKBENCH_TESTING"] = "1"
        os.environ.pop("LAWVER_DATABASE_URL", None)
        os.environ["LAWVER_WORKBENCH_USERS"] = "admin, alice"
        enabled = self._enabled()
        self.assertTrue(enabled("alice"))
        self.assertFalse(enabled("bob"))

    def test_production_without_database_url_stays_disabled(self):
        os.environ.pop("LAWVER_WORKBENCH_TESTING", None)
        os.environ.pop("LAWVER_DATABASE_URL", None)
        os.environ.pop("LAWVER_WORKBENCH_USERS", None)
        enabled = self._enabled()
        self.assertFalse(enabled("admin"))

    def test_configured_database_with_wildcard_enables_all(self):
        os.environ.pop("LAWVER_WORKBENCH_TESTING", None)
        os.environ["LAWVER_DATABASE_URL"] = "postgresql://lawver:pw@127.0.0.1:5432/lawver"
        os.environ["LAWVER_WORKBENCH_USERS"] = "*"
        enabled = self._enabled()
        self.assertTrue(enabled("admin"))


if __name__ == "__main__":
    unittest.main()
