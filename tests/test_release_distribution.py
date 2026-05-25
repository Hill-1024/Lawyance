"""
模块描述：Android APK 后端分发、缓存同步和下载限流回归测试。
"""

import hashlib
import importlib
import json
import os
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeResponse:
    def __init__(self, *, json_body=None, text="", content=b"", status_code=200):
        self._json_body = json_body
        self.text = text
        self.content = content
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class ReleaseDistributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_env = {
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "INITIAL_ADMIN_PASSWORD": os.environ.get("INITIAL_ADMIN_PASSWORD"),
            "LAWVER_DATA_DIR": os.environ.get("LAWVER_DATA_DIR"),
            "LAWVER_RELEASE_DIR": os.environ.get("LAWVER_RELEASE_DIR"),
            "LAWVER_APK_DOWNLOAD_RPM": os.environ.get("LAWVER_APK_DOWNLOAD_RPM"),
        }
        os.environ["SECRET_KEY"] = "r" * 32
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp.name
        os.environ.pop("LAWVER_RELEASE_DIR", None)
        self.release_sync = importlib.import_module("services.release_sync")
        self.release_sync.reset_download_rate_limits()

    def tearDown(self):
        self.release_sync.reset_download_rate_limits()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def _manifest(self, apk_bytes: bytes, version_code=1001):
        return {
            "platform": "android",
            "packageName": "moe.mutsumi.lawver",
            "versionName": "0.1.1",
            "versionCode": version_code,
            "apkUrl": "https://github.com/Hill-1024/Lawyance/releases/download/v0.1.1/Lawver-0.1.1.apk",
            "sha256": hashlib.sha256(apk_bytes).hexdigest(),
            "size": len(apk_bytes),
            "publishedAt": "2026-05-25T00:00:00Z",
        }

    def _app(self):
        routes = importlib.import_module("routes.releases")
        app = FastAPI()
        app.include_router(routes.router)
        return app

    def test_sync_latest_release_downloads_and_caches_valid_assets(self):
        apk = b"fake apk bytes"
        manifest = self._manifest(apk)
        release = {
            "published_at": "2026-05-25T00:00:00Z",
            "assets": [
                {"name": "android-version.json", "browser_download_url": "https://example.test/android-version.json"},
                {"name": "Lawver-0.1.1.apk", "browser_download_url": "https://example.test/Lawver-0.1.1.apk"},
            ],
        }

        def fake_get(url, **_kwargs):
            if url.endswith("/releases/latest"):
                return FakeResponse(json_body=release)
            if url.endswith("android-version.json"):
                return FakeResponse(text=json.dumps(manifest))
            if url.endswith("Lawver-0.1.1.apk"):
                return FakeResponse(content=apk)
            raise AssertionError(url)

        with mock.patch("services.release_sync.requests.get", side_effect=fake_get):
            status = self.release_sync.sync_latest_release()

        self.assertEqual(status["status"], "synced")
        cached = self.release_sync.cached_manifest()
        self.assertEqual(cached["versionCode"], 1001)
        self.assertEqual(cached["apkUrl"], "https://law.mutsumi.moe/api/releases/android/apk")
        with open(self.release_sync.cached_apk_path(), "rb") as f:
            self.assertEqual(f.read(), apk)

    def test_sync_rejects_invalid_sha_without_replacing_existing_cache(self):
        cache = self.release_sync.release_cache()
        cache.release_dir.mkdir(parents=True, exist_ok=True)
        old_apk = b"old apk"
        old_manifest = self._manifest(old_apk, version_code=1000)
        cache.apk_path.write_bytes(old_apk)
        cache.manifest_path.write_text(json.dumps(old_manifest), encoding="utf-8")

        new_apk = b"new apk"
        bad_manifest = self._manifest(new_apk, version_code=1001)
        bad_manifest["sha256"] = "0" * 64
        release = {
            "assets": [
                {"name": "android-version.json", "browser_download_url": "https://example.test/android-version.json"},
                {"name": "Lawver-0.1.1.apk", "browser_download_url": "https://example.test/Lawver-0.1.1.apk"},
            ],
        }

        def fake_get(url, **_kwargs):
            if url.endswith("/releases/latest"):
                return FakeResponse(json_body=release)
            if url.endswith("android-version.json"):
                return FakeResponse(text=json.dumps(bad_manifest))
            if url.endswith("Lawver-0.1.1.apk"):
                return FakeResponse(content=new_apk)
            raise AssertionError(url)

        with mock.patch("services.release_sync.requests.get", side_effect=fake_get):
            with self.assertRaises(self.release_sync.ReleaseSyncError):
                self.release_sync.sync_latest_release()

        self.assertEqual(cache.apk_path.read_bytes(), old_apk)
        self.assertEqual(self.release_sync.cached_manifest()["versionCode"], 1000)

    def test_public_release_routes_are_unauthenticated_and_rate_limited_for_apk_only(self):
        os.environ["LAWVER_APK_DOWNLOAD_RPM"] = "2"
        apk = b"apk"
        cache = self.release_sync.release_cache()
        cache.release_dir.mkdir(parents=True, exist_ok=True)
        cache.apk_path.write_bytes(apk)
        cache.manifest_path.write_text(json.dumps(self._manifest(apk)), encoding="utf-8")

        with TestClient(self._app(), base_url="https://law.mutsumi.moe") as client:
            latest = client.get("/api/releases/android/latest")
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(latest.json()["apkUrl"], "https://law.mutsumi.moe/api/releases/android/apk")

            self.assertEqual(client.get("/api/releases/android/apk").status_code, 200)
            self.assertEqual(client.get("/api/releases/android/apk").status_code, 200)
            limited = client.get("/api/releases/android/apk")
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(client.get("/api/releases/android/latest").status_code, 200)

    def test_release_routes_return_503_without_cache(self):
        with TestClient(self._app()) as client:
            self.assertEqual(client.get("/api/releases/android/latest").status_code, 503)
            self.assertEqual(client.get("/api/releases/android/apk").status_code, 503)


if __name__ == "__main__":
    unittest.main()
