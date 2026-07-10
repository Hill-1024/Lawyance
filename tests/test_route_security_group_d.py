"""Route-level regressions for court error handling and workspace filesystem boundaries."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import time
import types
import unittest

from fastapi.testclient import TestClient


TEST_SECRET = "d" * 32
ORIGIN = {"origin": "http://localhost:5173"}


def purge_runtime_modules() -> None:
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services"} or name.startswith("routes.") or name.startswith("services."):
            sys.modules.pop(name, None)


class RouteSecurityGroupDTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.workspace_root = os.path.join(self.tmp, "workspace")
        os.environ["SECRET_KEY"] = TEST_SECRET
        os.environ["INITIAL_ADMIN_PASSWORD"] = "bootstrap-password"
        os.environ["LAWVER_DATA_DIR"] = os.path.join(self.tmp, "data")
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
        os.environ.setdefault("LLM_MODEL", "test-model")
        os.environ.setdefault("DELI_APPID", "test-deli-app")
        os.environ.setdefault("DELI_SECRET", "test-deli-secret")
        os.environ.setdefault("PKU_ACCESS_TOKEN", "test-pku")
        os.environ.setdefault("QCC_ACCESS_TOKEN", "test-qcc")
        purge_runtime_modules()

        self.agent = importlib.import_module("agent")
        self.court_route = importlib.import_module("routes.court")
        self.workspace_route = importlib.import_module("routes.workspace")
        self.workspace_service = importlib.import_module("services.workspace_service")
        self.original_get_workspace_dirs = self.workspace_route.get_workspace_dirs

        def isolated_workspace_dirs(current_user: str, conversation_id: str) -> tuple[str, str]:
            scope = self.workspace_service.get_workspace_scope(current_user, conversation_id)
            return (
                os.path.join(self.workspace_root, "TEMP", scope),
                os.path.join(self.workspace_root, "Result", scope),
            )

        self.workspace_route.get_workspace_dirs = isolated_workspace_dirs
        self.client = TestClient(self.agent.app, base_url="http://localhost")
        login = self.client.post(
            "/api/login",
            json={"username": "admin", "password": "bootstrap-password"},
            headers=ORIGIN,
        )
        self.assertEqual(login.status_code, 200)

    async def asyncTearDown(self) -> None:
        self.client.close()
        self.workspace_route.get_workspace_dirs = self.original_get_workspace_dirs
        shutil.rmtree(self.tmp, ignore_errors=True)
        purge_runtime_modules()

    async def test_court_stream_does_not_disclose_raw_exception(self) -> None:
        marker = "provider-secret-token"
        original_prepare = self.court_route.prepare_court_turn
        original_run = self.court_route.run_court_turn_stream

        async def fake_prepare(*_args, **_kwargs):
            return types.SimpleNamespace()

        async def fake_run(_prepared):
            if False:
                yield None
            raise RuntimeError(marker)

        try:
            self.court_route.prepare_court_turn = fake_prepare
            self.court_route.run_court_turn_stream = fake_run
            response = self.client.post(
                "/api/court/turn",
                json={"court_session_id": "court-security"},
                headers=ORIGIN,
            )
        finally:
            self.court_route.prepare_court_turn = original_prepare
            self.court_route.run_court_turn_stream = original_run

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(marker, response.text)
        self.assertIn("庭审处理失败", response.text)
        self.assertTrue(response.text.rstrip().endswith("data: [DONE]"))

    async def test_court_memory_clear_offloads_blocking_memory_calls(self) -> None:
        original_call = self.court_route.call_memory_tool
        original_threadpool = getattr(self.court_route, "run_in_threadpool", None)
        offloaded: list[str] = []

        def fake_call(tool_name, _args, scope):
            self.assertEqual(tool_name, "clear_conversation_memory")
            return scope

        async def fake_threadpool(func, *args, **kwargs):
            offloaded.append(func.__name__)
            return func(*args, **kwargs)

        try:
            self.court_route.call_memory_tool = fake_call
            self.court_route.run_in_threadpool = fake_threadpool
            request = self.court_route.CourtMemoryClearRequest(court_session_id="court-offload")
            response = await self.court_route.clear_court_memory(request, current_user="admin")
        finally:
            self.court_route.call_memory_tool = original_call
            if original_threadpool is None:
                delattr(self.court_route, "run_in_threadpool")
            else:
                self.court_route.run_in_threadpool = original_threadpool

        self.assertEqual(response["status"], "success")
        self.assertEqual(offloaded, ["_clear_memory_scopes"])

    async def test_workspace_happy_path_remains_compatible(self) -> None:
        upload = self.client.post(
            "/api/upload",
            data={"conversation_id": "conv-happy"},
            files={"file": ("evidence.txt", b"legitimate evidence", "text/plain")},
            headers=ORIGIN,
        )
        self.assertEqual(upload.status_code, 200)
        file_path = upload.json()["file_path"]

        listing = self.client.get("/api/workspace/files", params={"conversation_id": "conv-happy"})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["name"] for item in listing.json()["files"]], ["evidence.txt"])

        download = self.client.get("/api/download", params={"file_path": file_path})
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"legitimate evidence")

        deletion = self.client.delete(
            "/api/workspace/file",
            params={"conversation_id": "conv-happy", "file_path": file_path},
            headers=ORIGIN,
        )
        self.assertEqual(deletion.status_code, 200)
        self.assertEqual(deletion.json(), {"status": "success"})

    async def test_workspace_rejects_parent_symlink_delete_escape(self) -> None:
        temp_dir, _ = self.workspace_route.get_workspace_dirs("admin", "conv-delete")
        outside_dir = os.path.join(self.tmp, "outside-delete")
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(outside_dir, exist_ok=True)
        outside_file = os.path.join(outside_dir, "secret.txt")
        with open(outside_file, "wb") as handle:
            handle.write(b"outside secret")
        try:
            os.symlink(outside_dir, os.path.join(temp_dir, "escape"), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

        response = self.client.delete(
            "/api/workspace/file",
            params={
                "conversation_id": "conv-delete",
                "file_path": os.path.join(temp_dir, "escape", "secret.txt"),
            },
            headers=ORIGIN,
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(os.path.isfile(outside_file))
        with open(outside_file, "rb") as handle:
            self.assertEqual(handle.read(), b"outside secret")

    async def test_workspace_rejects_symlink_download(self) -> None:
        temp_dir, _ = self.workspace_route.get_workspace_dirs("admin", "conv-download")
        os.makedirs(temp_dir, exist_ok=True)
        outside_file = os.path.join(self.tmp, "outside-download.txt")
        with open(outside_file, "wb") as handle:
            handle.write(b"do-not-disclose")
        link_path = os.path.join(temp_dir, "linked.txt")
        try:
            os.symlink(outside_file, link_path)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

        response = self.client.get("/api/download", params={"file_path": link_path})

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"do-not-disclose", response.content)

    async def test_workspace_cleanup_rejects_symlink_root_without_clearing_memory(self) -> None:
        temp_dir, _ = self.workspace_route.get_workspace_dirs("admin", "conv-clean")
        outside_dir = os.path.join(self.tmp, "outside-clean")
        os.makedirs(os.path.dirname(temp_dir), exist_ok=True)
        os.makedirs(outside_dir, exist_ok=True)
        sentinel = os.path.join(outside_dir, "keep.txt")
        with open(sentinel, "wb") as handle:
            handle.write(b"keep")
        try:
            os.symlink(outside_dir, temp_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

        memory_calls: list[str] = []
        original_call = self.workspace_route.call_memory_tool
        self.workspace_route.call_memory_tool = lambda _name, _args, scope: memory_calls.append(scope)
        try:
            response = self.client.delete("/api/workspace/conv-clean", headers=ORIGIN)
        finally:
            self.workspace_route.call_memory_tool = original_call

        self.assertEqual(response.status_code, 403)
        self.assertTrue(os.path.isfile(sentinel))
        self.assertEqual(memory_calls, [])

    async def test_workspace_rejects_unbounded_identifiers_and_file_collections(self) -> None:
        oversized_id = "x" * 161
        oversized_response = self.client.get(
            "/api/workspace/files",
            params={"conversation_id": oversized_id},
        )
        self.assertEqual(oversized_response.status_code, 422)

        temp_dir, _ = self.workspace_route.get_workspace_dirs("admin", "conv-many")
        os.makedirs(temp_dir, exist_ok=True)
        for index in range(3):
            with open(os.path.join(temp_dir, f"{index}.txt"), "wb") as handle:
                handle.write(b"x")

        original_limit = getattr(self.workspace_route, "MAX_WORKSPACE_FILES", None)
        self.workspace_route.MAX_WORKSPACE_FILES = 2
        try:
            listing = self.client.get("/api/workspace/files", params={"conversation_id": "conv-many"})
        finally:
            if original_limit is None:
                delattr(self.workspace_route, "MAX_WORKSPACE_FILES")
            else:
                self.workspace_route.MAX_WORKSPACE_FILES = original_limit

        self.assertEqual(listing.status_code, 413)
        self.assertNotIn("0.txt", listing.text)

    async def test_background_cleanup_skips_symlinked_user_directory(self) -> None:
        cleanup = importlib.import_module("services.workspace_cleanup")
        root = os.path.join(self.tmp, "cleanup-root")
        outside = os.path.join(root, "outside")
        temp_root = os.path.join(root, "TEMP")
        os.makedirs(os.path.join(outside, "conv"), exist_ok=True)
        os.makedirs(temp_root, exist_ok=True)
        sentinel = os.path.join(outside, "conv", "keep.txt")
        with open(sentinel, "wb") as handle:
            handle.write(b"keep")
        try:
            os.symlink(outside, os.path.join(temp_root, "attacker"), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

        old_cwd = os.getcwd()
        try:
            os.chdir(root)
            cleanup.cleanup_expired_workspace_dirs(time.time() + 1, set())
        finally:
            os.chdir(old_cwd)

        self.assertTrue(os.path.isfile(sentinel))


if __name__ == "__main__":
    unittest.main()
