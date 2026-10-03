"""
模块描述：credits 计量的回归测试——计价、账本、余额闸与分配。
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest


TEST_SECRET = "b" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"auth", "app_factory", "billing", "infra", "routes", "services"} or name.startswith(
            ("billing.", "infra.", "routes.", "services.")
        ):
            sys.modules.pop(name, None)


class BillingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        os.environ["LAWVER_WORKBENCH_TESTING"] = "1"
        os.environ.pop("LAWVER_DATABASE_URL", None)
        purge_runtime_modules()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def modules(self):
        return (
            importlib.import_module("auth"),
            importlib.import_module("billing.pricing"),
            importlib.import_module("billing.ledger"),
            importlib.import_module("billing.metering"),
            importlib.import_module("infra.account_store"),
        )


class PricingTests(BillingTestCase):
    def test_model_and_tool_prices_are_stable(self):
        _, pricing, _, _, _ = self.modules()
        # 8k prompt + 1.5k completion = 0.8 + 0.45 = 1.25 credits
        self.assertAlmostEqual(pricing.model_credits(8000, 1500), 1.25, places=6)
        # 工具默认价，具名工具按名字覆盖
        self.assertEqual(pricing.tool_price("unknown_tool"), 0.5)
        self.assertEqual(pricing.tool_price("web_search"), 1.0)
        self.assertEqual(pricing.tool_price("pkulaw_search"), 2.0)
        # 文档有下限，小文件也计费
        self.assertEqual(pricing.document_credits(0), 0.0)
        self.assertAlmostEqual(pricing.document_credits(1000), pricing.PRICE_DOCUMENT_MIN)

    def test_subscription_multiplier_discounts_usage(self):
        _, pricing, _, _, _ = self.modules()
        self.assertEqual(pricing.multiplier_for("go", "prepaid"), 1.0)
        self.assertEqual(pricing.multiplier_for("go", "monthly"), 0.8)
        self.assertEqual(pricing.multiplier_for("pro", "yearly"), 0.65)
        self.assertEqual(pricing.multiplier_for("business", "prepaid"), 0.6)
        # 账号级覆盖优先于套餐默认
        self.assertEqual(pricing.multiplier_for("go", "monthly", 0.5), 0.5)

    def test_plan_catalog_exposes_four_paid_tiers(self):
        _, pricing, _, _, _ = self.modules()
        ids = [plan["id"] for plan in pricing.plan_catalog()]
        self.assertEqual(ids, ["metered", "go", "pro", "max", "business"])


class MeteringTests(BillingTestCase):
    def test_turn_accumulates_and_charges_with_multiplier(self):
        _, pricing, _, metering, _ = self.modules()
        turn = metering.begin_turn("bob", multiplier=0.8, reason="测试")
        metering.record_model(8000, 1500, model="test-model")
        metering.record_tool("web_search")
        metering.record_document(20_000)
        # 1.25 + 1.0 + 0.4 = 2.65，乘 0.8 = 2.12
        self.assertAlmostEqual(turn.base_credits, 2.65, places=6)
        self.assertEqual(turn.charged_micro, pricing.credits(2.65 * 0.8))
        self.assertEqual(turn.tool_calls, 1)
        self.assertEqual(turn.model_calls, 1)
        metering.end_turn()

    def test_recording_without_a_turn_is_a_no_op(self):
        _, _, _, metering, _ = self.modules()
        metering.end_turn()
        # 没有开启轮次时不能抛异常，也不能凭空建账
        metering.record_model(100, 100)
        metering.record_tool("x")
        metering.record_document(10)
        self.assertIsNone(metering.current_turn())


class LedgerTests(BillingTestCase):
    def setUp(self):
        super().setUp()
        self.auth, self.pricing, self.ledger, self.metering, self.store = self.modules()
        self.auth.ensure_auth_store_ready()
        self.store.insert_user_record(
            {
                "username": "bob",
                "password_hash": self.auth.hash_password("bob-password"),
                "role": "user",
                "plan": "go",
                "billing_cycle": "monthly",
            }
        )
        # 余额只能从账本长出来：直接写 credits_balance 会让对账把差额抹掉。
        self.ledger.grant("bob", 10, reason="开户赠送", actor="admin")

    def test_settle_deducts_balance_and_writes_daily_usage(self):
        turn = self.metering.begin_turn("bob", multiplier=0.8, reason="工作台任务", ref_id="run-1")
        self.metering.record_model(10_000, 2_000)
        self.metering.record_tool("web_search")
        summary = self.ledger.settle(turn)
        self.metering.end_turn()

        # (1.0 + 0.6 + 1.0) × 0.8 = 2.08
        self.assertAlmostEqual(summary["credits"], 2.08, places=2)
        self.assertAlmostEqual(
            self.pricing.as_credits(self.ledger.balance("bob")), 7.92, places=2
        )
        rows = self.ledger.usage_rows("bob")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tool_calls"], 1)
        self.assertEqual(rows[0]["turns"], 1)
        self.assertAlmostEqual(rows[0]["credits"], 2.08, places=2)
        # 账本里有明细可对账
        entry = self.ledger.recent_ledger("bob")[0]
        self.assertEqual(entry["kind"], "charge")
        self.assertEqual(entry["ref_id"], "run-1")
        self.assertEqual(entry["meta"]["tool_calls"], 1)

    def test_empty_turn_writes_nothing(self):
        before = len(self.ledger.recent_ledger("bob"))
        turn = self.metering.begin_turn("bob")
        self.assertEqual(self.ledger.settle(turn), {})
        # 空轮次不产生任何 charge 流水
        self.assertEqual(len(self.ledger.recent_ledger("bob")), before)
        self.assertFalse(
            [row for row in self.ledger.recent_ledger("bob") if row["kind"] == "charge"]
        )

    def test_reconcile_rebuilds_balance_from_ledger(self):
        # bob 开户已有 10（见 setUp），再充值 5、修正 -3 → 账本合计 12
        self.ledger.grant("bob", 5, reason="充值", actor="admin")
        self.ledger.grant("bob", -3, kind="adjust", reason="修正", actor="admin")
        result = self.ledger.reconcile("bob")
        self.assertAlmostEqual(result["ledger_total"], 12.0, places=2)
        self.assertAlmostEqual(
            self.pricing.as_credits(self.ledger.balance("bob")), 12.0, places=2
        )

    def test_can_spend_blocks_when_balance_is_exhausted(self):
        os.environ["LAWVER_BILLING_ENFORCE"] = "1"
        self.addCleanup(os.environ.pop, "LAWVER_BILLING_ENFORCE", None)
        allowed, reason = self.ledger.can_spend("bob")
        self.assertTrue(allowed, reason)
        self.ledger.grant("bob", -10, kind="adjust", reason="清零")
        allowed, reason = self.ledger.can_spend("bob")
        self.assertFalse(allowed)
        self.assertIn("credits 不足", reason)

    def test_sudo_account_is_never_blocked(self):
        os.environ["LAWVER_BILLING_ENFORCE"] = "1"
        self.addCleanup(os.environ.pop, "LAWVER_BILLING_ENFORCE", None)
        allowed, reason = self.ledger.can_spend("admin")
        self.assertTrue(allowed, reason)

    def test_suspended_account_cannot_spend_even_with_credits(self):
        os.environ["LAWVER_BILLING_ENFORCE"] = "1"
        self.addCleanup(os.environ.pop, "LAWVER_BILLING_ENFORCE", None)
        self.store.update_user("bob", status="suspended")
        allowed, reason = self.ledger.can_spend("bob")
        self.assertFalse(allowed)
        self.assertIn("停用", reason)

    def test_allocation_moves_credits_from_parent_to_child(self):
        self.store.update_user("bob", plan="business")
        self.store.insert_user_record(
            {
                "username": "kid",
                "password_hash": self.auth.hash_password("kid-password"),
                "role": "user",
                "owner": "bob",
            }
        )
        ok, message = self.ledger.transfer_to_child("bob", "kid", 4, actor="bob")
        self.assertTrue(ok, message)
        self.assertAlmostEqual(self.pricing.as_credits(self.ledger.balance("bob")), 6.0, places=2)
        self.assertAlmostEqual(self.pricing.as_credits(self.ledger.balance("kid")), 4.0, places=2)
        # 一对流水，两边都能查到
        self.assertEqual(self.ledger.recent_ledger("bob")[0]["kind"], "allocation_out")
        self.assertEqual(self.ledger.recent_ledger("kid")[0]["kind"], "allocation_in")

    def test_recording_mode_does_not_block_a_zero_balance_account(self):
        """默认（未打开拦截）下，余额为 0 的普通账号也能正常发起任务，只是记账。"""
        self.ledger.grant("bob", -10, kind="adjust", reason="清零")
        allowed, reason = self.ledger.can_spend("bob")
        self.assertTrue(allowed, reason)
        self.assertAlmostEqual(self.pricing.as_credits(self.ledger.balance("bob")), 0.0, places=2)

    def test_allocation_reads_the_parent_balance_under_a_row_lock(self):
        """先判余额再扣减必须锁住母账号行，否则两次并发划转会读到同一旧余额、一起透支。

        测试库是 SQLite（方言会省略 FOR UPDATE），这里按 PostgreSQL 方言编译实际语句来确认加锁。
        """
        from unittest import mock

        from sqlalchemy.dialects import postgresql

        self.store.update_user("bob", plan="business")
        self.store.insert_user_record(
            {
                "username": "kid",
                "password_hash": self.auth.hash_password("kid-password"),
                "role": "user",
                "owner": "bob",
            }
        )
        compiled = []
        original = self.ledger.balance_micro

        def spy(session, username, **kwargs):
            real_scalar = session.scalar

            def capture(statement, *args, **kw):
                compiled.append(str(statement.compile(dialect=postgresql.dialect())))
                return real_scalar(statement, *args, **kw)

            with mock.patch.object(session, "scalar", capture):
                return original(session, username, **kwargs)

        with mock.patch.object(self.ledger, "balance_micro", spy):
            ok, message = self.ledger.transfer_to_child("bob", "kid", 1, actor="bob")
        self.assertTrue(ok, message)
        self.assertEqual(len(compiled), 1)
        self.assertIn("FOR UPDATE", compiled[0])

    def test_allocation_refuses_when_parent_is_short(self):
        self.store.update_user("bob", plan="business")
        self.store.insert_user_record(
            {
                "username": "kid",
                "password_hash": self.auth.hash_password("kid-password"),
                "role": "user",
                "owner": "bob",
            }
        )
        ok, message = self.ledger.transfer_to_child("bob", "kid", 999, actor="bob")
        self.assertFalse(ok)
        self.assertIn("余额不足", message)


class SubaccountStatusTests(BillingTestCase):
    """Business 母账号可以停用/启用自己名下的子账号，但管不到别人的。"""

    def setUp(self):
        super().setUp()
        self.auth, self.pricing, self.ledger, self.metering, self.store = self.modules()
        self.auth.ensure_auth_store_ready()
        self.auth.upsert_account(
            "admin", "biz", "biz-password-1", role="user", plan="business", max_users=5
        )
        # 子账号由母账号自己创建，owner 才指向 biz。
        self.auth.upsert_account("biz", "kid", "kid-password-1", role="user")
        self.auth.upsert_account("admin", "outsider", "outsider-pass-1", role="user")

    def test_business_parent_can_suspend_and_restore_own_child(self):
        ok, message = self.auth.set_account_status("biz", "kid", "suspended")
        self.assertTrue(ok, message)
        self.assertEqual(self.auth.get_user_record("kid")["status"], "suspended")
        ok, message = self.auth.set_account_status("biz", "kid", "active")
        self.assertTrue(ok, message)
        self.assertEqual(self.auth.get_user_record("kid")["status"], "active")

    def test_suspending_a_subaccount_revokes_its_sessions(self):
        """停用必须真的把设备踢下线。

        这条专门盯一个曾经静默失效的路径：撤销会话时漏传了 list_sessions 的
        仅关键字参数，异常又被调用方的 try/except 吞掉，于是「改密码/停用踢下线」
        看起来成功、实际什么都没发生。
        """
        ok, _, sid, _ = self.auth.create_session("kid", client="web")
        self.assertTrue(ok)
        self.assertEqual(self.auth.verify_token(sid), "kid")

        ok, message = self.auth.set_account_status("biz", "kid", "suspended")
        self.assertTrue(ok, message)
        self.assertIsNone(self.auth.verify_token(sid))

    def test_business_parent_cannot_touch_other_accounts(self):
        ok, message = self.auth.set_account_status("biz", "outsider", "suspended")
        self.assertFalse(ok)
        self.assertIn("只能管理自己创建的账号", message)

    def test_non_business_user_cannot_suspend_at_all(self):
        self.store.update_user("outsider", plan="go")
        ok, message = self.auth.set_account_status("outsider", "kid", "suspended")
        self.assertFalse(ok)
        self.assertIn("权限不足", message)

    def test_business_subaccount_inherits_the_parent_online_limit(self):
        """与 admin 代建的 user 同一规则：子账号的在线上限继承母账号的 user_max_online。"""
        self.store.update_user("biz", user_max_online=2)
        ok, message = self.auth.upsert_account("biz", "kid2", "kid2-password-1", role="user")
        self.assertTrue(ok, message)
        record = self.auth.get_user_record("kid2")
        self.assertEqual(record["owner"], "biz")
        self.assertEqual(record["role"], "user")
        self.assertEqual(record["max_online"], 2)
        # 母账号不能借建号给子账号开子配额。
        self.assertIsNone(record["max_users"])
        self.assertIsNone(record["user_max_online"])


if __name__ == "__main__":
    unittest.main()
