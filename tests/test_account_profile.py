"""
模块描述：账号个人资料（uid / 自定义 ID / 头像）的 API 回归。

uid 在引导与迁移后都必须存在且稳定；custom_id 的校验/冲突/清除走 /api/profile；
头像上传走 /api/profile/avatar，公开读取走 /api/avatars/{uid}（按 version 失效缓存）。
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

TEST_SECRET = "x" * 32
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082"
)


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services", "infra"} or name.startswith("routes.") or name.startswith("services.") or name.startswith("infra."):
            sys.modules.pop(name, None)


class AccountProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp
        purge_runtime_modules()
        self.agent = importlib.import_module("agent")
        self.auth = importlib.import_module("auth")
        self.client = TestClient(self.agent.app, base_url="http://localhost")
        response = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.uid = None

    def tearDown(self):
        purge_runtime_modules()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_user(self, username: str, password: str = "user-password-x") -> None:
        ok, message = self.auth.upsert_account("admin", username, password)
        assert ok, message

    def test_uid_is_assigned_and_stable_across_sessions(self):
        first = self.client.get("/api/session").json()
        second = self.client.get("/api/session").json()
        self.assertTrue(first["authenticated"])
        self.assertRegex(first["uid"], r"^[0-9a-f]{32}$")
        self.assertEqual(first["uid"], second["uid"])
        self.assertEqual(first["plan"], "metered")
        self.assertEqual(first["avatar_version"], 0)
        self.assertIsNone(first["custom_id"])
        # 存量账号在首次读取前就该有 uid：直接查库确认，不依赖会话触发。
        record = self.auth.get_user_record("admin")
        self.assertRegex(record["uid"], r"^[0-9a-f]{32}$")

    def test_custom_id_validation_and_conflict(self):
        # 大小写会被静默归一成小写（展示句柄语义，GitHub 同款）；
        # 真正非法的是长度、首尾字符与保留字。
        normalized = self.client.patch("/api/profile", json={"custom_id": "Hill-1024"})
        self.assertEqual(normalized.status_code, 200)
        self.assertEqual(normalized.json()["profile"]["custom_id"], "hill-1024")

        for bad in ("-abc", "a", "a" * 40, "admin", "abc-"):
            response = self.client.patch("/api/profile", json={"custom_id": bad})
            self.assertEqual(response.status_code, 422, bad)
            self.assertIn("detail", response.json())

        self._create_user("second-user")
        self.client.post("/api/logout")
        self.client.post(
            "/api/login", json={"username": "second-user", "password": "user-password-x"}
        )
        conflict = self.client.patch("/api/profile", json={"custom_id": "hill-1024"})
        self.assertEqual(conflict.status_code, 409)

        # 清除：置空后回退到 username 展示，且别人可以用这个 ID。
        cleared = self.client.patch("/api/profile", json={"custom_id": None})
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["profile"]["custom_id"])

    def test_avatar_upload_serve_and_delete(self):
        missing = self.client.get("/api/avatars/" + "0" * 32)
        self.assertEqual(missing.status_code, 404)

        bad_type = self.client.put(
            "/api/profile/avatar",
            files={"file": ("a.gif", PNG_1PX, "image/gif")},
        )
        self.assertEqual(bad_type.status_code, 422)

        uploaded = self.client.put(
            "/api/profile/avatar",
            files={"file": ("a.png", PNG_1PX, "image/png")},
        )
        self.assertEqual(uploaded.status_code, 200)
        profile = uploaded.json()["profile"]
        self.assertEqual(profile["avatar_version"], 1)

        uid = profile["uid"]
        served = self.client.get(f"/api/avatars/{uid}")
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["content-type"], "image/png")
        self.assertIn("max-age", served.headers.get("cache-control", ""))

        removed = self.client.delete("/api/profile/avatar")
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["profile"]["avatar_version"], 2)
        gone = self.client.get(f"/api/avatars/{uid}")
        self.assertEqual(gone.status_code, 404)

    def test_custom_id_unique_constraint_race_is_a_conflict_not_a_500(self):
        """先查后写之间被人抢注时，唯一约束兜底也要回 409，而不是 IntegrityError 冒成 500。"""
        import contextlib
        from unittest import mock

        from sqlalchemy.exc import IntegrityError

        store = importlib.import_module("infra.account_store")

        @contextlib.contextmanager
        def racing_transaction(*_args, **_kwargs):
            session = mock.Mock()
            session.execute.return_value.first.return_value = None  # 预检查没看到占用者
            yield session
            raise IntegrityError("UPDATE accounts", {}, Exception("UNIQUE constraint failed"))

        real_set_custom_id = store.set_custom_id

        def racing_set_custom_id(username, custom_id):
            # 只在这一次写入里换掉事务：鉴权、读资料等其余查库照常走真实库。
            with mock.patch.object(store, "transaction", racing_transaction):
                return real_set_custom_id(username, custom_id)

        with mock.patch.object(store, "set_custom_id", racing_set_custom_id):
            response = self.client.patch("/api/profile", json={"custom_id": "taken-handle"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("已被占用", response.json()["detail"])

    def test_custom_id_save_failure_is_reported_not_a_500(self):
        """存储层返回未知结果时 update_custom_id 也必须是 (ok, error) 二元组。"""
        from unittest import mock

        with mock.patch.object(self.auth.auth_store, "set_custom_id", return_value="error"):
            response = self.client.patch("/api/profile", json={"custom_id": "some-handle"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("保存失败", response.json()["detail"])

    def test_oversized_avatar_is_rejected_with_a_bounded_read(self):
        """超限头像要拒绝，且读取必须限长：整文件 read() 会把任意大小的上传搬进内存。"""
        from unittest import mock

        from starlette.datastructures import UploadFile

        original_read = UploadFile.read
        sizes = []

        async def spy_read(upload, size=-1):
            sizes.append(size)
            return await original_read(upload, size)

        oversized = PNG_1PX + b"\0" * (self.auth.AVATAR_MAX_BYTES + 16)
        with mock.patch.object(UploadFile, "read", spy_read):
            response = self.client.put(
                "/api/profile/avatar",
                files={"file": ("big.png", oversized, "image/png")},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("1 MB", response.json()["detail"])
        self.assertTrue(sizes)
        self.assertTrue(all(0 < size <= self.auth.AVATAR_MAX_BYTES + 1 for size in sizes), sizes)

    def test_avatar_requires_auth(self):
        self.client.post("/api/logout")
        response = self.client.put(
            "/api/profile/avatar",
            files={"file": ("a.png", PNG_1PX, "image/png")},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
