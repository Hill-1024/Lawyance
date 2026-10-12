"""
模块描述：开屏公告时区回归测试——带时区 datetime 写入口必须归一为 UTC 再落库。

SQLite 方言不保存 DateTime 的 offset：+08:00 原样入库会被读回成 +00:00 的同墙钟
时刻，时间漂移 8 小时。写入口统一 astimezone(utc) 后，两种方言读回的都是同一时刻。
"""

import importlib
import os
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient


TEST_SECRET = "b" * 32
LOCAL_ORIGIN = "http://localhost:5173"


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra"} or name.startswith("routes.") or name.startswith("services.") or name.startswith("infra."):
            sys.modules.pop(name, None)


class AnnouncementTimezoneTests(unittest.TestCase):
    def setUp(self):
        # 进程级缓存的引擎可能握着旧 sqlite 文件；Windows 不允许删除被占用文件。
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp.name
        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.client = TestClient(self.agent.app, base_url="http://localhost")
        login = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(login.status_code, 200)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()
        purge_runtime_modules()

    def _create(self, payload):
        response = self.client.post(
            "/api/admin/announcements",
            json=payload,
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["announcement"]

    def test_create_normalizes_aware_datetimes_to_utc(self):
        announcement = self._create({
            "title": "维护窗口",
            "starts_at": "2026-01-01T08:00:00+08:00",
            "ends_at": "2026-01-01T12:00:00+08:00",
        })

        # +08:00 写入，读回必须是等价 UTC 时刻，而不是 +00:00 的同墙钟。
        self.assertEqual(announcement["starts_at"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(announcement["ends_at"], "2026-01-01T04:00:00+00:00")

    def test_patch_normalizes_aware_datetimes_to_utc(self):
        announcement = self._create({"title": "原公告"})

        patched = self.client.patch(
            f"/api/admin/announcements/{announcement['id']}",
            json={"starts_at": "2026-02-01T10:00:00+08:00", "ends_at": "2026-02-01T18:00:00+08:00"},
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        body = patched.json()["announcement"]
        self.assertEqual(body["starts_at"], "2026-02-01T02:00:00+00:00")
        self.assertEqual(body["ends_at"], "2026-02-01T10:00:00+00:00")

    def test_round_trip_keeps_same_instant_across_persistence(self):
        """入库再读回（admin 列表走 DB）仍是同一时刻。"""
        announcement = self._create({
            "title": "时区回归",
            "starts_at": "2026-03-01T20:30:00+08:00",
        })

        listing = self.client.get(
            "/api/admin/announcements",
            headers={"origin": LOCAL_ORIGIN},
        )
        self.assertEqual(listing.status_code, 200)
        rows = {row["id"]: row for row in listing.json()["announcements"]}
        self.assertEqual(rows[announcement["id"]]["starts_at"], "2026-03-01T12:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
