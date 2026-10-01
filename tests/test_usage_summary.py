"""
模块描述：自助用量控制台接口（/api/usage/summary）的回归——窗口夹取、补零序列、
合计与余额字段，以及 credits 耗尽时前端弹窗所依赖的形状。
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


TEST_SECRET = "u" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra", "billing"} or name.startswith(
            ("routes.", "services.", "infra.", "billing.")
        ):
            sys.modules.pop(name, None)


class UsageSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        os.environ["LAWVER_WORKBENCH_TESTING"] = "1"
        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.auth = importlib.import_module("auth")
        self.ledger = importlib.import_module("billing.ledger")
        self.client = TestClient(self.agent.app, base_url="http://localhost")
        assert self.client.post(
            "/api/login", json={"username": "admin", "password": "bootstrap-password"}
        ).status_code == 200

    def tearDown(self):
        purge_runtime_modules()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _record_usage(self, day_offset: int, credits_micro: int, turns: int = 2):
        """直接写 usage_daily：接口只负责读，写入形状由 billing 层保证。"""
        from billing.models import UsageDaily
        from infra.database import transaction

        self.ledger.usage_rows("admin", days=1)  # 触发建表
        day = datetime.now(timezone.utc).date() - timedelta(days=day_offset)
        with transaction() as session:
            session.add(
                UsageDaily(
                    username="admin",
                    day=day,
                    prompt_tokens=100 + day_offset,
                    completion_tokens=50,
                    tool_calls=1,
                    documents=0,
                    document_chars=0,
                    turns=turns,
                    credits_spent=credits_micro,
                )
            )

    def test_series_is_continuous_zero_filled_and_totals_sum(self):
        self._record_usage(0, 1_500_000)          # 今天
        self._record_usage(4, 2_500_000)          # 5 天前
        response = self.client.get("/api/usage/summary?days=7")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["days"], 7)
        self.assertEqual(len(data["series"]), 7)
        self.assertEqual(data["series"][-1]["day"], datetime.now(timezone.utc).date().isoformat())
        # 缺的天补零；有的天数值进来了
        credits_list = [entry["credits"] for entry in data["series"]]
        self.assertEqual(credits_list[-1], 1500.0)   # micro → credits
        self.assertEqual(credits_list[-5], 2500.0)
        zero_days = [c for c in credits_list if c == 0]
        self.assertEqual(len(zero_days), 5)
        self.assertEqual(data["totals"]["credits"], 4000.0)
        self.assertEqual(data["totals"]["tool_calls"], 2)
        self.assertEqual(data["totals"]["prompt_tokens"], 100 * 2 + 4 + 0)  # 今天的 100 + 5天前的 104；缺零天为 0
        self.assertEqual(data["balance"], 0)

    def test_days_is_clamped_to_90(self):
        response = self.client.get("/api/usage/summary?days=500")
        self.assertEqual(response.status_code, 422)  # Query ge/le 直接校验
        response = self.client.get("/api/usage/summary?days=90")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["series"]), 90)

    def test_requires_auth(self):
        self.client.post("/api/logout")
        response = self.client.get("/api/usage/summary")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
