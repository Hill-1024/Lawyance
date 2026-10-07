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

from infra.password_hashing import hash_password


TEST_SECRET = "x" * 32
LOCAL_ORIGIN = "http://localhost:5173"


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra"} or name.startswith("routes.") or name.startswith("services.") or name.startswith("infra."):
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
        # 迁移后 account.json 改名归档，不再作为权威数据源。
        self.assertFalse(os.path.exists(legacy_path))
        self.assertTrue(glob.glob(os.path.join(self.tmp, "account.json.imported-*")))
        # 迁移来的密码仍可登录。
        self.assertEqual(auth.authenticate_user("bob", "legacy-user-password"), (True, "登录成功"))

    def test_insecure_default_admin_hash_is_rejected_after_migration(self):
        legacy_path = os.path.join(self.tmp, "account.json")
        with open(legacy_path, "w", encoding="utf-8") as handle:
            json.dump({"admin": {"hash": "cf632ecdd2c9b4e67cd76de4db6b785d$12b8bd1ec5414d7a46abf6b92a4bc0319ca7b9662bba71bc9776dcbefc4c0177", "role": "admin"}}, handle)

        # 引导现在是惰性的（导入期不连库，缺配置时服务照常起），
        # 于是「不安全默认管理员」要在第一次真正用到账号库时炸出来。
        with self.assertRaises(RuntimeError):
            self.import_auth().get_user_record("admin")


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

    def test_billing_fields_at_creation_are_sudo_only(self):
        """admin 建号不能自带 plan/计费方式/倍率/开户额度，否则能铸造 business 子账号或绕开计价。"""
        self._make_admin()
        ok, _ = self.auth.upsert_account(
            "alice",
            "bob",
            "bob-password",
            plan="business",
            billing_cycle="monthly",
            credit_multiplier=0.01,
            initial_credits=1000,
        )
        self.assertTrue(ok)
        record = self.auth.get_user_record("bob")
        # 存储层会补默认值：admin 传入的计费字段被忽略，落回默认套餐。
        self.assertEqual(record["plan"], "metered")
        self.assertEqual(record["billing_cycle"], "prepaid")
        self.assertIsNone(record["credit_multiplier"])
        self.assertEqual(record["credits_balance"], 0)  # 开户额度同样只认 sudo

        # sudo 建号仍然可以指定计费字段（与更新路径同一策略）。
        ok, _ = self.auth.upsert_account(
            "admin",
            "carol",
            "carol-password",
            plan="business",
            billing_cycle="monthly",
            credit_multiplier=0.5,
        )
        self.assertTrue(ok)
        carol = self.auth.get_user_record("carol")
        self.assertEqual(carol["plan"], "business")
        self.assertEqual(carol["billing_cycle"], "monthly")
        self.assertEqual(carol["credit_multiplier"], 0.5)

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

        self.assertIsNone(self.auth.verify_token(first_sid))
        self.assertEqual(self.auth.verify_token(second_sid), "bob")
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
        token = sid

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
        token = sid
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

            # sudo 可以直接踢下线（按列表摘要定位，原 sid 不出管理接口）。
            kicked = self.sudo_client.delete(
                f"/api/admin/sessions/{bob_sessions[0]['sid_fingerprint']}",
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

    def test_unlock_endpoint_is_scoped_to_owned_accounts(self):
        """解锁端点：sudo 不限；admin 只能解锁自己名下的账号，越权回 403。"""
        self.assertEqual(
            self._create(self.sudo_client, "alice", "alice-password", role="admin", max_users=2).status_code,
            200,
        )
        self.assertEqual(self._create(self.sudo_client, "outsider", "outsider-password").status_code, 200)
        admin_client = TestClient(self.agent.app, base_url="http://localhost")
        try:
            self._login(admin_client, "alice", "alice-password")
            self.assertEqual(self._create(admin_client, "bob", "bob-password").status_code, 200)

            # 与应用同一份 auth 模块（setUp 里导入 agent 时重新加载过）。
            auth = importlib.import_module("auth")
            # 锁住 bob：同一来源连续输错到硬上限，来源桶即触发锁定。
            for _ in range(auth.LOCKOUT_FAIL_LIMIT):
                auth.authenticate_user("bob", "wrong-password", "198.51.100.77")
            self.assertTrue(auth.check_lockout("bob", "198.51.100.77"))

            own = admin_client.post("/api/admin/accounts/bob/unlock", headers={"origin": LOCAL_ORIGIN})
            self.assertEqual(own.status_code, 200, own.text)
            self.assertIsNone(auth.check_lockout("bob", "198.51.100.77"))

            foreign = admin_client.post("/api/admin/accounts/outsider/unlock", headers={"origin": LOCAL_ORIGIN})
            self.assertEqual(foreign.status_code, 403)
        finally:
            admin_client.close()

        anyone = self.sudo_client.post("/api/admin/accounts/outsider/unlock", headers={"origin": LOCAL_ORIGIN})
        self.assertEqual(anyone.status_code, 200, anyone.text)


class AccountContractRegressionTests(AuthTestCase):
    """T18/T20/T24/T4 回归：账号管理 API 的契约不被默认值/泄露/列宽击穿。"""

    def setUp(self):
        super().setUp()
        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.auth = importlib.import_module("auth")
        self.sudo_client = TestClient(self.agent.app, base_url="http://localhost")
        response = self.sudo_client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        try:
            self.sudo_client.close()
        finally:
            super().tearDown()

    def test_upsert_without_role_keeps_existing_role(self):
        """T20：重置密码省略 role 时不得把 admin/sudo 静默降级为 user。"""
        ok, message = self.auth.upsert_account(
            "admin", "boss", "boss-password-1", role="admin", max_users=3
        )
        self.assertTrue(ok, message)
        response = self.sudo_client.post(
            "/api/admin/accounts",
            json={"username": "boss", "password": "boss-password-2"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.auth.get_user_role("boss"), "admin")

        # 省略 role 的新建账号仍然落默认 user。
        created = self.sudo_client.post(
            "/api/admin/accounts",
            json={"username": "newcomer", "password": "newcomer-password"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(self.auth.get_user_role("newcomer"), "user")

    def test_plan_upsert_clears_pending_downgrade_and_is_visible(self):
        """T18：客服改套餐必须清掉预约降级；列表要能看到挂着预约的账号。"""
        ok, message = self.auth.upsert_account("admin", "u1", "u1-password-1", plan="pro")
        self.assertTrue(ok, message)
        ok, _, effective = self.auth.schedule_plan_change("u1", "metered")
        self.assertTrue(ok, message)
        self.assertIsNotNone(effective)

        # sudo 明确写入新套餐 = 推翻预约：不清的话结算日一到 go 会被 metered 覆盖。
        ok, message = self.auth.upsert_account("admin", "u1", "u1-password-1", plan="go")
        self.assertTrue(ok, message)
        record = self.auth.get_user_record("u1")
        self.assertIsNone(record.get("pending_plan"))
        self.assertEqual(record.get("plan"), "go")

        # 结算日已过也不会再把套餐打回去（懒应用走 store 层，与读取路径同源）。
        from datetime import datetime, timedelta, timezone

        account_store = importlib.import_module("infra.account_store")
        applied = account_store.apply_pending_plan_if_due(
            "u1", now=datetime.now(timezone.utc) + timedelta(days=400)
        )
        self.assertIsNone(applied)
        self.assertEqual(self.auth.get_user_record("u1").get("plan"), "go")

        accounts = self.auth.list_accounts("admin")
        by_name = {item["username"]: item for item in accounts}
        self.assertIn("pending_plan", by_name["u1"])

        # 有预约的账号在列表里可见（客服能发现挂着降级的账号）。
        ok, _, _ = self.auth.schedule_plan_change("u1", "metered")
        self.assertTrue(ok)
        accounts = self.auth.list_accounts("admin")
        by_name = {item["username"]: item for item in accounts}
        self.assertEqual(by_name["u1"]["pending_plan"], "metered")
        self.assertIsNotNone(by_name["u1"]["pending_effective_at"])

    def test_admin_sessions_list_never_exposes_raw_sid(self):
        """T24：列表只出不可逆摘要；下线设备按摘要定位。"""
        ok, message = self.auth.upsert_account("admin", "bob", "bob-password-1")
        self.assertTrue(ok, message)
        other = TestClient(self.agent.app, base_url="http://localhost")
        try:
            login = other.post(
                "/api/login",
                json={"username": "bob", "password": "bob-password-1"},
                headers={"origin": LOCAL_ORIGIN},
            )
            self.assertEqual(login.status_code, 200)

            sessions = self.sudo_client.get("/api/admin/sessions").json()["sessions"]
            self.assertTrue(sessions)
            for item in sessions:
                self.assertNotIn("sid", item, "原 sid 就是会话凭据，不能出现在管理接口")
                self.assertRegex(item["sid_fingerprint"], r"^[0-9a-f]{16}$")

            bob_rows = [item for item in sessions if item["username"] == "bob"]
            self.assertEqual(len(bob_rows), 1)
            fingerprint = bob_rows[0]["sid_fingerprint"]

            # 摘要不能反推回会话：bob 的原 sid 仍可用（未被误吊销）。
            self.assertEqual(other.get("/api/verify_auth").status_code, 200)

            revoke = self.sudo_client.delete(
                f"/api/admin/sessions/{fingerprint}",
                headers={"origin": LOCAL_ORIGIN},
            )
            self.assertEqual(revoke.status_code, 200, revoke.text)
            self.assertEqual(other.get("/api/verify_auth").status_code, 401)
        finally:
            other.close()

    def test_login_truncates_client_and_user_agent_to_column_width(self):
        """T4：超长 UA（PostgreSQL varchar(400)）与任意长 x-lawver-client 不得 500。"""
        response = self.sudo_client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={
                "origin": LOCAL_ORIGIN,
                "user-agent": "U" * 512,
                "x-lawver-client": "C" * 500,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

        account_store = importlib.import_module("infra.account_store")
        rows = account_store.list_sessions(
            usernames=["admin"], online_window=self.auth.ONLINE_WINDOW_SECONDS
        )
        # 中间件会 touch 旧会话，last_seen 排序不可靠：按 client 特征找本次登录的行。
        latest = next(row for row in rows if (row["client"] or "").startswith("CCCC"))
        self.assertEqual(len(latest["user_agent"] or ""), 400)
        self.assertEqual(len(latest["client"] or ""), 40)
