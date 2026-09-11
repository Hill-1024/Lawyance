"""
模块描述：账号层级、配额与在线设备限制的回归测试，覆盖 JSON 迁移、sudo/admin/user 边界与会话踢下线。
"""

import glob
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

from services.password_hashing import hash_password


TEST_SECRET = "x" * 32
LOCAL_ORIGIN = "http://localhost:5173"


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services"} or name.startswith("routes.") or name.startswith("services."):
            sys.modules.pop(name, None)


class AuthTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_env = {
            key: os.environ.get(key)
            for key in (
                "SECRET_KEY",
                "INITIAL_ADMIN_PASSWORD",
                "LAWVER_DATA_DIR",
                "LAWVER_ONLINE_LIMIT_ACTION",
            )
        }
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        os.environ.pop("LAWVER_ONLINE_LIMIT_ACTION", None)
        purge_runtime_modules()

    def tearDown(self):
        purge_runtime_modules()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def import_auth(self):
        return importlib.import_module("auth")

    def create_account(self, auth, actor, username, password, **kwargs):
        ok, message = auth.upsert_account(actor, username, password, **kwargs)
        self.assertTrue(ok, message)
        return username


class LegacyMigrationTests(AuthTestCase):
    def test_legacy_account_json_is_imported_roles_mapped_and_archived(self):
        legacy_path = os.path.join(self.tmp, "account.json")
        with open(legacy_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "admin": {"hash": hash_password("legacy-admin-password"), "role": "admin"},
                    "operator": {"hash": hash_password("legacy-operator-password"), "role": "admin"},
                    "bob": {"hash": hash_password("legacy-user-password"), "role": "user", "auth_version": 3},
                },
                handle,
            )

        auth = self.import_auth()

        # 旧 admin 等级映射为 sudo，普通用户保持 user。
        self.assertEqual(auth.get_user_role("admin"), "sudo")
        self.assertEqual(auth.get_user_role("operator"), "sudo")
        self.assertEqual(auth.get_user_role("bob"), "user")
        self.assertEqual(auth.get_user_record("bob")["auth_version"], 3)
        # 迁移后 account.json 改名归档，不再作为权威数据源。
        self.assertFalse(os.path.exists(legacy_path))
        self.assertTrue(glob.glob(os.path.join(self.tmp, "account.json.imported-*")))
        # 迁移来的密码仍可登录。
        self.assertEqual(auth.authenticate_user("bob", "legacy-user-password"), (True, "登录成功"))

    def test_insecure_default_admin_hash_is_rejected_after_migration(self):
        legacy_path = os.path.join(self.tmp, "account.json")
        with open(legacy_path, "w", encoding="utf-8") as handle:
            json.dump({"admin": {"hash": "cf632ecdd2c9b4e67cd76de4db6b785d$12b8bd1ec5414d7a46abf6b92a4bc0319ca7b9662bba71bc9776dcbefc4c0177", "role": "admin"}}, handle)

        with self.assertRaises(RuntimeError):
            self.import_auth()


class RoleHierarchyTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.auth = self.import_auth()

    def _make_admin(self, name="alice", max_users=2, user_max_online=1):
        self.create_account(
            self.auth, "admin", name, f"{name}-password", role="admin", max_users=max_users, user_max_online=user_max_online
        )
        return name

    def test_admin_cannot_create_admin_or_sudo(self):
        self._make_admin()
        for role in ("admin", "sudo"):
            ok, message = self.auth.upsert_account("alice", f"x-{role}", "some-password", role=role)
            self.assertFalse(ok)
            self.assertIn("只能创建普通用户", message)

    def test_admin_cannot_set_online_limit(self):
        self._make_admin()
        ok, message = self.auth.upsert_account("alice", "bob", "bob-password", max_online=5)
        self.assertFalse(ok)
        self.assertIn("不能设置最大在线数量", message)

    def test_admin_created_user_inherits_m_and_cannot_change_it(self):
        self._make_admin(max_users=3, user_max_online=2)
        self.create_account(self.auth, "alice", "bob", "bob-password")
        self.assertEqual(self.auth.get_user_record("bob")["max_online"], 2)
        # admin 重置密码时不改变在线上限。
        ok, _ = self.auth.upsert_account("alice", "bob", "new-bob-password")
        self.assertTrue(ok)
        self.assertEqual(self.auth.get_user_record("bob")["max_online"], 2)

    def test_user_quota_n_is_enforced_and_freed_by_deletion(self):
        self._make_admin(max_users=2)
        self.create_account(self.auth, "alice", "bob", "bob-password")
        self.create_account(self.auth, "alice", "carol", "carol-password")

        ok, message = self.auth.upsert_account("alice", "dave", "dave-password")
        self.assertFalse(ok)
        self.assertIn("已达可创建用户上限", message)

        self.assertTrue(self.auth.delete_account("carol", "alice")[0])
        ok, _ = self.auth.upsert_account("alice", "dave", "dave-password")
        self.assertTrue(ok)

    def test_admin_cannot_touch_another_admins_users(self):
        self._make_admin("alice")
        self._make_admin("dave")
        self.create_account(self.auth, "alice", "bob", "bob-password")

        ok, message = self.auth.upsert_account("dave", "bob", "overwrite-password")
        self.assertFalse(ok)
        self.assertIn("只能管理自己创建的账号", message)
        self.assertFalse(self.auth.delete_account("bob", "dave")[0])
        self.assertNotIn("bob", [item["username"] for item in self.auth.list_accounts("dave")])

    def test_plain_user_cannot_manage_accounts(self):
        self.create_account(self.auth, "admin", "bob", "bob-password")
        ok, _ = self.auth.upsert_account("bob", "carol", "carol-password")
        self.assertFalse(ok)
        self.assertEqual(self.auth.list_accounts("bob"), [])

    def test_sudo_can_set_n_m_and_override_user_limit(self):
        self._make_admin(max_users=1, user_max_online=1)
        self.create_account(self.auth, "alice", "bob", "bob-password")

        ok, _ = self.auth.set_account_limits("admin", "alice", max_users=5, user_max_online=3)
        self.assertTrue(ok)
        self.assertEqual(self.auth.get_user_record("alice")["max_users"], 5)
        self.assertEqual(self.auth.get_user_record("alice")["user_max_online"], 3)

        # 管理员本人无权调整配额。
        ok, message = self.auth.set_account_limits("alice", "bob", max_online=9)
        self.assertFalse(ok)
        self.assertIn("只有超级管理员", message)

        ok, _ = self.auth.set_account_limits("admin", "bob", max_online=4)
        self.assertTrue(ok)
        self.assertEqual(self.auth.get_user_record("bob")["max_online"], 4)

    def test_builtin_admin_cannot_be_demoted_or_deleted(self):
        ok, message = self.auth.upsert_account("admin", "admin", "new-admin-password", role="user")
        self.assertFalse(ok)
        self.assertIn("不能将管理员账号降级", message)
        self.assertFalse(self.auth.delete_account("admin", "admin")[0])


class OnlineDeviceLimitTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        self.auth = self.import_auth()

    def test_second_login_kicks_the_oldest_session(self):
        self.create_account(self.auth, "admin", "bob", "bob-password", max_online=1)

        ok, _, first_sid, evicted = self.auth.create_session("bob", client="web")
        self.assertTrue(ok)
        self.assertEqual(evicted, [])

        ok, message, second_sid, evicted = self.auth.create_session("bob", client="web")
        self.assertTrue(ok, message)
        self.assertEqual(evicted, [first_sid])

        self.assertIsNone(self.auth.verify_token(self.auth.create_token("bob", first_sid)))
        self.assertEqual(self.auth.verify_token(self.auth.create_token("bob", second_sid)), "bob")
        self.assertEqual(self.auth.count_online("bob"), 1)

    def test_unlimited_account_allows_many_sessions(self):
        self.create_account(self.auth, "admin", "bob", "bob-password")
        for _ in range(5):
            ok, message, _sid, evicted = self.auth.create_session("bob", client="web")
            self.assertTrue(ok, message)
            self.assertEqual(evicted, [])
        self.assertEqual(self.auth.count_online("bob"), 5)

    def test_logout_frees_a_slot(self):
        self.create_account(self.auth, "admin", "bob", "bob-password", max_online=1)
        ok, _, sid, _ = self.auth.create_session("bob", client="web")
        self.assertTrue(ok)
        token = self.auth.create_token("bob", sid)

        self.assertTrue(self.auth.revoke_token_session(token))
        self.assertEqual(self.auth.count_online("bob"), 0)
        self.assertIsNone(self.auth.verify_token(token))

        ok, message, _sid2, _ = self.auth.create_session("bob", client="web")
        self.assertTrue(ok, message)

    def test_reject_action_refuses_new_login(self):
        os.environ["LAWVER_ONLINE_LIMIT_ACTION"] = "reject"
        purge_runtime_modules()
        auth = importlib.import_module("auth")
        self.create_account(auth, "admin", "bob", "bob-password", max_online=1)

        ok, _, _sid, _ = auth.create_session("bob", client="web")
        self.assertTrue(ok)
        ok, message, sid, _ = auth.create_session("bob", client="web")
        self.assertFalse(ok)
        self.assertIsNone(sid)
        self.assertIn("最多允许 1 台设备", message)

    def test_password_reset_revokes_sessions(self):
        self.create_account(self.auth, "admin", "bob", "bob-password")
        ok, _, sid, _ = self.auth.create_session("bob", client="web")
        self.assertTrue(ok)
        token = self.auth.create_token("bob", sid)
        self.assertEqual(self.auth.verify_token(token), "bob")

        self.assertTrue(self.auth.upsert_account("admin", "bob", "brand-new-password")[0])

        self.assertIsNone(self.auth.verify_token(token))
        self.assertEqual(self.auth.authenticate_user("bob", "brand-new-password"), (True, "登录成功"))


class AuthRouteScopeTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.sudo_client = TestClient(self.agent.app, base_url="http://localhost")
        self._login(self.sudo_client, "admin", "bootstrap-password")

    def tearDown(self):
        try:
            self.sudo_client.close()
        finally:
            super().tearDown()

    def _login(self, client: TestClient, username: str, password: str):
        response = client.post(
            "/api/login",
            json={"username": username, "password": password},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def _create(self, actor_client: TestClient, username: str, password: str, role: str = "user", **extra):
        response = actor_client.post(
            "/api/admin/accounts",
            json={"username": username, "password": password, "role": role, **extra},
            headers={"origin": LOCAL_ORIGIN},
        )
        return response

    def test_admin_scope_and_sudo_only_endpoints(self):
        self.assertEqual(
            self._create(self.sudo_client, "alice", "alice-password", role="admin", max_users=1, user_max_online=2).status_code,
            200,
        )

        admin_client = TestClient(self.agent.app, base_url="http://localhost")
        try:
            self._login(admin_client, "alice", "alice-password")

            # 日志与系统设置仅 sudo 可见。
            self.assertEqual(admin_client.get("/api/admin/logs").status_code, 403)
            self.assertEqual(admin_client.get("/api/settings").status_code, 403)

            # admin 只能创建普通用户，且受 n 限制。
            first = self._create(admin_client, "bob", "bob-password")
            self.assertEqual(first.status_code, 200, first.text)
            second = self._create(admin_client, "carol", "carol-password")
            self.assertEqual(second.status_code, 400)
            self.assertIn("已达可创建用户上限", second.json()["detail"])

            forbidden_role = self._create(admin_client, "dave", "dave-password", role="admin")
            self.assertEqual(forbidden_role.status_code, 400)

            # admin 无法自定配额。
            self.assertEqual(
                admin_client.patch(
                    "/api/admin/accounts/bob/limits",
                    json={"max_online": 9},
                    headers={"origin": LOCAL_ORIGIN},
                ).status_code,
                403,
            )

            # 账号列表只包含自己创建的用户。
            accounts = admin_client.get("/api/admin/accounts").json()["accounts"]
            self.assertEqual([item["username"] for item in accounts], ["bob"])

            # 新用户继承 m=2，但 admin 不能改。
            self.assertEqual(accounts[0]["max_online"], 2)
        finally:
            admin_client.close()

        # sudo 可以调整该 admin 的 n / m。
        patched = self.sudo_client.patch(
            "/api/admin/accounts/alice/limits",
            json={"max_users": 3, "user_max_online": 1},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(patched.status_code, 200, patched.text)

    def test_plain_user_cannot_reach_staff_endpoints(self):
        self.assertEqual(self._create(self.sudo_client, "bob", "bob-password").status_code, 200)
        user_client = TestClient(self.agent.app, base_url="http://localhost")
        try:
            self._login(user_client, "bob", "bob-password")
            self.assertEqual(user_client.get("/api/admin/accounts").status_code, 403)
            self.assertEqual(user_client.get("/api/admin/sessions").status_code, 403)
            self.assertEqual(user_client.get("/api/admin/logs").status_code, 403)
            info = user_client.get("/api/verify_auth").json()
            self.assertEqual(info["role"], "user")
        finally:
            user_client.close()

    def test_online_limit_enforced_across_login_clients(self):
        self.assertEqual(
            self._create(self.sudo_client, "bob", "bob-password", max_online=1).status_code,
            200,
        )

        first = TestClient(self.agent.app, base_url="http://localhost")
        second = TestClient(self.agent.app, base_url="http://localhost")
        try:
            self._login(first, "bob", "bob-password")
            self.assertEqual(first.get("/api/verify_auth").status_code, 200)

            self._login(second, "bob", "bob-password")
            # 新登录踢掉旧设备，旧客户端令牌立即失效。
            self.assertEqual(first.get("/api/verify_auth").status_code, 401)
            self.assertEqual(second.get("/api/verify_auth").status_code, 200)

            sessions = self.sudo_client.get("/api/admin/sessions").json()["sessions"]
            bob_sessions = [item for item in sessions if item["username"] == "bob"]
            self.assertEqual(len(bob_sessions), 1)
            self.assertTrue(bob_sessions[0]["online"])

            # sudo 可以直接踢下线。
            kicked = self.sudo_client.delete(
                f"/api/admin/sessions/{bob_sessions[0]['sid']}",
                headers={"origin": LOCAL_ORIGIN},
            )
            self.assertEqual(kicked.status_code, 200, kicked.text)
            self.assertEqual(second.get("/api/verify_auth").status_code, 401)
        finally:
            first.close()
            second.close()

    def test_verify_auth_reports_admin_quota(self):
        self._create(self.sudo_client, "alice", "alice-password", role="admin", max_users=4, user_max_online=2)
        admin_client = TestClient(self.agent.app, base_url="http://localhost")
        try:
            self._login(admin_client, "alice", "alice-password")
            info = admin_client.get("/api/verify_auth").json()
            self.assertEqual(info["role"], "admin")
            self.assertEqual(info["max_users"], 4)
            self.assertEqual(info["user_max_online"], 2)
        finally:
            admin_client.close()
