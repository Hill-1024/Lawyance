"""SPA fallback regressions for cwd independence and symlink containment."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import spa


class SpaRouteHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_dist_dir = spa.DIST_DIR
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dist = self.root / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<main>spa-index</main>", encoding="utf-8")
        spa.DIST_DIR = self.dist
        app = FastAPI()
        app.include_router(spa.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        spa.DIST_DIR = self.original_dist_dir
        self.tmp.cleanup()

    def test_fallback_is_independent_of_process_working_directory(self) -> None:
        other_cwd = self.root / "other"
        other_cwd.mkdir()
        previous_cwd = os.getcwd()
        try:
            os.chdir(other_cwd)
            response = self.client.get("/settings/help")
        finally:
            os.chdir(previous_cwd)

        self.assertEqual(response.status_code, 200)
        self.assertIn("spa-index", response.text)

    def test_symlinked_asset_cannot_escape_dist_root(self) -> None:
        secret = self.root / "secret.txt"
        secret.write_text("do-not-disclose", encoding="utf-8")
        try:
            (self.dist / "leak.txt").symlink_to(secret)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

        response = self.client.get("/leak.txt")

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("do-not-disclose", response.text)

    def test_api_fallback_stays_404(self) -> None:
        response = self.client.get("/api/not-real")
        self.assertEqual(response.status_code, 404)

    def test_missing_asset_is_404_instead_of_html_fallback(self) -> None:
        (self.dist / "assets").mkdir()

        response = self.client.get("/assets/index-gone.js")

        # 回退成 HTML 会让浏览器把 HTML 当 JS 解析，表现为只加载出基本 HTML。
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("spa-index", response.text)

    def test_hashed_assets_are_immutable_while_html_revalidates(self) -> None:
        assets = self.dist / "assets"
        assets.mkdir()
        (assets / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
        (self.dist / "sw.js").write_text("// sw", encoding="utf-8")

        asset = self.client.get("/assets/index-abc123.js")
        fallback = self.client.get("/settings/help")
        sw = self.client.get("/sw.js")

        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers["cache-control"], "public, max-age=31536000, immutable")
        # index.html 一旦被启发式缓存，用户会长期拿到引用旧哈希资源的旧页面。
        self.assertEqual(fallback.headers["cache-control"], "no-cache")
        self.assertEqual(sw.headers["cache-control"], "no-cache")


if __name__ == "__main__":
    unittest.main()
