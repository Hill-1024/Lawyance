"""
模块描述：后端生命周期启动法库缓存准备回归测试。
"""

import asyncio
import importlib
import os
import sys
import tempfile
import unittest

from fastapi import FastAPI


TEST_SECRET = "z" * 32


def purge_runtime_modules():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services"} or name.startswith("routes.") or name.startswith("services."):
            sys.modules.pop(name, None)


class LawCacheStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = self.tmp.name
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("PKU_ACCESS_TOKEN", "test-pku")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")
        purge_runtime_modules()
        self.app_factory = importlib.import_module("app_factory")

    def tearDown(self):
        self.tmp.cleanup()
        purge_runtime_modules()

    def test_lifespan_prepares_law_cache_before_background_cleanup(self):
        events = []

        async def fake_prepare(app: FastAPI):
            events.append("law_cache")
            app.state.law_cache_status = {"mode": "test"}

        def fake_start(_app: FastAPI):
            events.append("workspace_start")

        async def fake_stop(_app: FastAPI):
            events.append("workspace_stop")

        original_prepare = self.app_factory.law_cache.prepare_on_startup
        original_start = self.app_factory.workspace_cleanup.start
        original_stop = self.app_factory.workspace_cleanup.stop
        try:
            self.app_factory.law_cache.prepare_on_startup = fake_prepare
            self.app_factory.workspace_cleanup.start = fake_start
            self.app_factory.workspace_cleanup.stop = fake_stop

            async def exercise_lifespan():
                app = FastAPI()
                async with self.app_factory.lifespan(app):
                    self.assertEqual(events, ["law_cache", "workspace_start"])
                    self.assertEqual(app.state.law_cache_status, {"mode": "test"})

            asyncio.run(exercise_lifespan())
        finally:
            self.app_factory.law_cache.prepare_on_startup = original_prepare
            self.app_factory.workspace_cleanup.start = original_start
            self.app_factory.workspace_cleanup.stop = original_stop

        self.assertEqual(events, ["law_cache", "workspace_start", "workspace_stop"])


if __name__ == "__main__":
    unittest.main()
