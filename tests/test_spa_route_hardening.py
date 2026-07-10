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


if __name__ == "__main__":
    unittest.main()
