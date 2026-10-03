"""
模块描述：套餐自助变更（预约降级/切回按量 + 取消变更）的回归。

口径：只放行降级与切回按量（metered），升级与 business 走客服/组织通道；
预约在下一结算周期生效（无周期到期日则取下个自然月），生效前权益不变，
可随时取消。到点的变更由读取路径懒应用（profile/credits/usage）。
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


TEST_SECRET = "p" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra", "billing"} or name.startswith(
            ("routes.", "services.", "infra.", "billing.")
        ):
            sys.modules.pop(name, None)


class SubscriptionChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        os.environ["LAWVER_WORKBENCH_TESTING"] = "1"
        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.auth = importlib.import_module("auth")
        self.store = importlib.import_module("infra.account_store")
        self.client = TestClient(self.agent.app, base_url="http://localhost")
        assert self.client.post(
            "/api/login", json={"username": "admin", "password": "bootstrap-password"}
        ).status_code == 200
        # 造一个 pro 订阅户（带周期到期日）与一个 go 户
        for name, plan in (("pro-user", "pro"), ("go-user", "go")):
            assert self.auth.upsert_account("admin", name, "user-password-x")
            self.store.update_user(name, plan=plan)
        self.store.update_user(
            "pro-user",
            last_grant_at=datetime.now(timezone.utc),
            grant_expire_at=datetime.now(timezone.utc) + timedelta(days=20),
        )

    def tearDown(self):
        purge_runtime_modules()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _login(self, username, password="user-password-x"):
        assert self.client.post(
            "/api/login", json={"username": username, "password": password}
        ).status_code == 200

    def test_downgrade_is_scheduled_for_next_settlement_and_lazy_applied(self):
        self._login("pro-user")
        response = self.client.post(
            "/api/subscription/change", json={"target_plan": "go"}
        )
        self.assertEqual(response.status_code, 200)
        profile = response.json()["profile"]
        self.assertEqual(profile["plan"], "pro")            # 当前权益未变
        self.assertEqual(profile["pending_plan"], "go")
        self.assertIsNotNone(profile["pending_effective_at"])

        # 生效前：读取路径不落地
        self.assertEqual(self.client.get("/api/profile").json()["plan"], "pro")

        # 时间推过结算日：懒应用把 plan 换成 go、清掉预约
        # （pending_effective_at 不在 update_user 白名单里，走专用 setter）
        self.store.set_pending_plan("pro-user", "go", datetime.now(timezone.utc) - timedelta(days=1))
        profile = self.client.get("/api/profile").json()
        self.assertEqual(profile["plan"], "go")
        self.assertIsNone(profile["pending_plan"])

    def test_switch_to_metered_and_cancel_change(self):
        self._login("pro-user")
        response = self.client.post(
            "/api/subscription/change", json={"target_plan": "metered"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["profile"]["pending_plan"], "metered")

        cancelled = self.client.post("/api/subscription/cancel-change")
        self.assertEqual(cancelled.status_code, 200)
        self.assertIsNone(cancelled.json()["profile"]["pending_plan"])

    def test_switch_to_metered_drops_the_subscription_discount_when_applied(self):
        """切回按量落地后计费方式必须回到 prepaid：倍率由 billing_cycle 决定，
        只改 plan 的话用户会一直按月付 0.8 的折扣扣费。"""
        self.store.update_user("pro-user", billing_cycle="monthly")
        self._login("pro-user")
        self.assertEqual(self.client.get("/api/credits").json()["multiplier"], 0.8)
        self.assertEqual(
            self.client.post("/api/subscription/change", json={"target_plan": "metered"}).status_code,
            200,
        )
        self.store.set_pending_plan("pro-user", "metered", datetime.now(timezone.utc) - timedelta(days=1))

        credits = self.client.get("/api/credits").json()
        self.assertEqual(credits["plan"], "metered")
        self.assertEqual(credits["billing_cycle"], "prepaid")
        self.assertEqual(credits["multiplier"], 1.0)

    def test_downgrade_between_paid_tiers_keeps_the_billing_cycle(self):
        self.store.update_user("pro-user", billing_cycle="monthly")
        self.store.set_pending_plan("pro-user", "go", datetime.now(timezone.utc) - timedelta(days=1))
        self._login("pro-user")
        credits = self.client.get("/api/credits").json()
        self.assertEqual(credits["plan"], "go")
        self.assertEqual(credits["billing_cycle"], "monthly")
        self.assertEqual(credits["multiplier"], 0.8)

    def test_missing_plan_is_treated_as_metered(self):
        """plan 缺省按 metered 理解：此前误取角色常量 "user"，任何变更都报「未知的目标套餐」。"""
        from unittest import mock

        with mock.patch.object(self.auth, "get_user_record", return_value={"username": "x", "plan": None}):
            ok, message, _ = self.auth.schedule_plan_change("x", "go")
        self.assertFalse(ok)
        self.assertIn("升级", message)

    def test_upgrade_is_rejected_here(self):
        self._login("go-user")
        for target in ("pro", "max", "business"):
            response = self.client.post(
                "/api/subscription/change", json={"target_plan": target}
            )
            self.assertEqual(response.status_code, 422, target)

    def test_same_plan_is_rejected(self):
        self._login("pro-user")
        response = self.client.post(
            "/api/subscription/change", json={"target_plan": "pro"}
        )
        self.assertEqual(response.status_code, 422)

    def test_requires_auth(self):
        self.client.post("/api/logout")
        response = self.client.post(
            "/api/subscription/change", json={"target_plan": "metered"}
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
