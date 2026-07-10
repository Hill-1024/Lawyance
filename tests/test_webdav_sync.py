"""
模块描述：WebDAV 数据同步中转 API 测试，覆盖正常路径、SSRF 拦截和鉴权缺失。
"""

import base64
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, REPO_ROOT)

TEST_SECRET = "w" * 32
TEST_ADMIN_PW = "webdav-test-admin-pw-9876"
_ORIGIN = {"origin": "http://localhost:5173"}


def _purge():
    for name in list(sys.modules):
        if name in {"agent", "app_factory", "auth", "routes", "services"} or \
                name.startswith("routes.") or name.startswith("services."):
            sys.modules.pop(name, None)


def _make_fresh_client(tmp_dir: str):
    """在隔离的临时目录中创建 FastAPI 测试客户端，保证 auth 状态干净。"""
    from fastapi.testclient import TestClient
    os.environ["SECRET_KEY"] = TEST_SECRET
    os.environ["INITIAL_ADMIN_PASSWORD"] = TEST_ADMIN_PW
    os.environ["LAWVER_DATA_DIR"] = tmp_dir
    os.environ.setdefault("API_KEY", "test-key")
    os.environ.setdefault("BASE_URL", "http://127.0.0.1/v1")
    os.environ.setdefault("LLM_MODEL", "test-model")
    _purge()
    app_factory = importlib.import_module("app_factory")
    app = app_factory.create_app()
    # base_url=localhost → secure_cookie_for_request 返回 False → 非 secure cookie，TestClient 正常回传
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def _login(client):
    """登录后 TestClient 自动持久化 cookie，无需手动传递。"""
    resp = client.post(
        "/api/login",
        json={"username": "admin", "password": TEST_ADMIN_PW},
        headers=_ORIGIN,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"


class WebDavSSRFTests(unittest.TestCase):
    """SSRF 防护：私有/环回/保留 IP 必须被拒绝。"""

    def setUp(self):
        os.environ.pop("LAWVER_WEBDAV_ALLOW_PRIVATE", None)
        self.tmp = tempfile.mkdtemp()
        self.client = _make_fresh_client(self.tmp)
        _login(self.client)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _purge()

    def _post(self, endpoint, payload):
        return self.client.post(f"/api/webdav/{endpoint}", json=payload, headers=_ORIGIN)

    def _cfg(self, url):
        return {"url": url, "username": "u", "password": "p", "directory": "/Lawver/"}

    def test_loopback_rejected(self):
        with patch("routes.webdav.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(None, None, None, None, ("127.0.0.1", 0))]
            resp = self._post("test", {"config": self._cfg("https://evil.local")})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("私有", resp.json().get("detail", ""))

    def test_private_10_rejected(self):
        with patch("routes.webdav.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(None, None, None, None, ("10.0.0.1", 0))]
            resp = self._post("test", {"config": self._cfg("https://internal.corp")})
        self.assertEqual(resp.status_code, 400)

    def test_private_192_rejected(self):
        with patch("routes.webdav.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(None, None, None, None, ("192.168.1.1", 0))]
            resp = self._post("list", {"config": self._cfg("https://nas.home")})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_scheme_rejected(self):
        resp = self._post("test", {"config": self._cfg("ftp://example.com")})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("协议", resp.json().get("detail", ""))

    def test_url_userinfo_and_query_rejected(self):
        resp = self._post("test", {"config": self._cfg("https://user:pass@example.com/dav?token=secret")})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("不允许", resp.json().get("detail", ""))

    def test_allow_private_env_bypasses_check(self):
        os.environ["LAWVER_WEBDAV_ALLOW_PRIVATE"] = "1"
        mock_resp = MagicMock()
        mock_resp.status_code = 207
        with patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("test", {"config": self._cfg("http://192.168.1.100")})
        os.environ.pop("LAWVER_WEBDAV_ALLOW_PRIVATE", None)
        self.assertNotEqual(resp.status_code, 400)

    def test_second_resolution_rejects_rebound_private_address(self):
        from fastapi import HTTPException
        from routes import webdav

        with patch(
            "routes.webdav.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("127.0.0.1", 443))],
        ), patch("routes.webdav.requests.Session.request") as remote_request:
            with self.assertRaises(HTTPException) as captured:
                webdav._request_remote(
                    "GET",
                    "https://rebind.example/backup.json",
                    timeout=1,
                    allow_redirects=False,
                )

        self.assertEqual(captured.exception.status_code, 400)
        remote_request.assert_not_called()

    def test_pinned_connection_keeps_hostname_but_connects_to_vetted_ip(self):
        from routes import webdav

        connection = webdav._PinnedHTTPSConnection(
            "dav.example.com",
            port=443,
            timeout=1,
            pinned_ip="93.184.216.34",
        )
        with patch("urllib3.util.connection.create_connection", return_value=MagicMock()) as create_connection:
            connection._new_conn()

        self.assertEqual(connection.host, "dav.example.com")
        self.assertEqual(create_connection.call_args.args[0], ("93.184.216.34", 443))


class WebDavAuthTests(unittest.TestCase):
    """未登录用户必须收到 401。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_fresh_client(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _purge()

    def _cfg(self):
        return {"url": "https://dav.example.com", "username": "u", "password": "p", "directory": "/Lawver/"}

    def _post(self, endpoint, payload):
        return self.client.post(f"/api/webdav/{endpoint}", json=payload, headers=_ORIGIN)

    def test_test_requires_auth(self):
        resp = self._post("test", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 401)

    def test_list_requires_auth(self):
        resp = self._post("list", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 401)

    def test_upload_requires_auth(self):
        resp = self._post("upload", {
            "config": self._cfg(), "filename": "x.json", "data_b64": base64.b64encode(b"{}").decode()
        })
        self.assertEqual(resp.status_code, 401)

    def test_download_requires_auth(self):
        resp = self._post("download", {"config": self._cfg(), "filename": "x.json"})
        self.assertEqual(resp.status_code, 401)

    def test_delete_requires_auth(self):
        resp = self._post("delete", {"config": self._cfg(), "filename": "x.json"})
        self.assertEqual(resp.status_code, 401)


class WebDavHappyPathTests(unittest.TestCase):
    """正常路径：mock requests，验证端点逻辑。"""

    def setUp(self):
        os.environ.pop("LAWVER_WEBDAV_ALLOW_PRIVATE", None)
        self.tmp = tempfile.mkdtemp()
        self.client = _make_fresh_client(self.tmp)
        _login(self.client)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        _purge()

    def _post(self, endpoint, payload):
        return self.client.post(f"/api/webdav/{endpoint}", json=payload, headers=_ORIGIN)

    def _cfg(self):
        return {"url": "https://dav.example.com", "username": "u", "password": "p", "directory": "/Lawver/"}

    def _dns_public(self):
        return patch("routes.webdav.socket.getaddrinfo",
                     return_value=[(None, None, None, None, ("93.184.216.34", 0))])

    def test_test_ok_directory_exists(self):
        mock_resp = MagicMock(); mock_resp.status_code = 207
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("test", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertFalse(resp.json()["created_directory"])

    def test_test_creates_directory_on_404(self):
        propfind_resp = MagicMock(); propfind_resp.status_code = 404
        mkcol_resp = MagicMock(); mkcol_resp.status_code = 201
        with self._dns_public(), patch("routes.webdav._request_remote", side_effect=[propfind_resp, mkcol_resp]):
            resp = self._post("test", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["created_directory"])

    def test_list_parses_propfind(self):
        xml_body = """<?xml version="1.0"?>
        <D:multistatus xmlns:D="DAV:">
          <D:response>
            <D:href>/Lawver/</D:href>
            <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
          </D:response>
          <D:response>
            <D:href>/Lawver/lawver_backup_2025-01-01_120000.json</D:href>
            <D:propstat><D:prop>
              <D:getcontentlength>1234</D:getcontentlength>
              <D:getlastmodified>Wed, 01 Jan 2025 12:00:00 GMT</D:getlastmodified>
              <D:resourcetype/>
            </D:prop></D:propstat>
          </D:response>
        </D:multistatus>"""
        mock_resp = MagicMock(); mock_resp.status_code = 207
        mock_resp.iter_content.return_value = [xml_body.encode()]
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("list", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 200)
        files = resp.json()["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["filename"], "lawver_backup_2025-01-01_120000.json")
        self.assertEqual(files[0]["size"], 1234)

    def test_upload_ok(self):
        mock_resp = MagicMock(); mock_resp.status_code = 201
        data_b64 = base64.b64encode(
            json.dumps({"version": 3, "conversations": [], "courtSessions": [], "settings": {}}).encode()
        ).decode()
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("upload", {
                "config": self._cfg(),
                "filename": "lawver_backup_2025-01-01_120000.json",
                "data_b64": data_b64,
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_upload_rejects_path_traversal(self):
        data_b64 = base64.b64encode(b"{}").decode()
        with self._dns_public():
            resp = self._post("upload", {
                "config": self._cfg(), "filename": "../evil.json", "data_b64": data_b64,
            })
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_non_json_extension(self):
        data_b64 = base64.b64encode(b"{}").decode()
        with self._dns_public():
            resp = self._post("upload", {
                "config": self._cfg(), "filename": "backup.lawver", "data_b64": data_b64,
            })
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_malformed_base64_before_remote_request(self):
        with self._dns_public(), patch("routes.webdav._request_remote") as remote_put:
            resp = self._post("upload", {
                "config": self._cfg(), "filename": "backup.json", "data_b64": "!!!!",
            })
        self.assertEqual(resp.status_code, 422)
        remote_put.assert_not_called()

    def test_upload_rejects_oversized(self):
        big = base64.b64encode(b"x" * (26 * 1024 * 1024)).decode()
        with self._dns_public():
            resp = self._post("upload", {
                "config": self._cfg(), "filename": "big.json", "data_b64": big,
            })
        self.assertEqual(resp.status_code, 413)

    def test_download_ok(self):
        payload = json.dumps({"version": 3}).encode()
        mock_resp = MagicMock(); mock_resp.status_code = 200
        mock_resp.iter_content = lambda chunk_size: iter([payload])
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("download", {"config": self._cfg(), "filename": "lawver_backup.json"})
        self.assertEqual(resp.status_code, 200)
        decoded = base64.b64decode(resp.json()["data_b64"])
        self.assertEqual(json.loads(decoded)["version"], 3)

    def test_delete_ok(self):
        mock_resp = MagicMock(); mock_resp.status_code = 204
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("delete", {"config": self._cfg(), "filename": "lawver_backup.json"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_remote_webdav_401_does_not_expire_lawver_session(self):
        mock_resp = MagicMock(); mock_resp.status_code = 401
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("test", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("鉴权", resp.json().get("detail", ""))

    def test_list_root_directory_not_skipped(self):
        cfg_root = self._cfg().copy()
        cfg_root["directory"] = "/"
        xml_body = """<?xml version="1.0"?>
        <D:multistatus xmlns:D="DAV:">
          <D:response>
            <D:href>/</D:href>
            <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
          </D:response>
          <D:response>
            <D:href>/lawver_backup_2025-01-01_120000.json</D:href>
            <D:propstat><D:prop>
              <D:getcontentlength>1234</D:getcontentlength>
              <D:getlastmodified>Wed, 01 Jan 2025 12:00:00 GMT</D:getlastmodified>
              <D:resourcetype/>
            </D:prop></D:propstat>
          </D:response>
        </D:multistatus>"""
        mock_resp = MagicMock(); mock_resp.status_code = 207
        mock_resp.iter_content.return_value = [xml_body.encode()]
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("list", {"config": cfg_root})
        self.assertEqual(resp.status_code, 200)
        files = resp.json()["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["filename"], "lawver_backup_2025-01-01_120000.json")

    def test_list_unquotes_filenames(self):
        xml_body = """<?xml version="1.0"?>
        <D:multistatus xmlns:D="DAV:">
          <D:response>
            <D:href>/Lawver/</D:href>
            <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
          </D:response>
          <D:response>
            <D:href>/Lawver/lawver%20backup%20%E4%B8%AD%E6%96%87.json</D:href>
            <D:propstat><D:prop>
              <D:getcontentlength>1234</D:getcontentlength>
              <D:getlastmodified>Wed, 01 Jan 2025 12:00:00 GMT</D:getlastmodified>
              <D:resourcetype/>
            </D:prop></D:propstat>
          </D:response>
        </D:multistatus>"""
        mock_resp = MagicMock(); mock_resp.status_code = 207
        mock_resp.iter_content.return_value = [xml_body.encode()]
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("list", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 200)
        files = resp.json()["files"]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["filename"], "lawver backup 中文.json")

    def test_list_rejects_oversized_propfind_response(self):
        mock_resp = MagicMock(); mock_resp.status_code = 207
        mock_resp.iter_content.return_value = [b"x" * (2 * 1024 * 1024 + 1)]
        with self._dns_public(), patch("routes.webdav._request_remote", return_value=mock_resp):
            resp = self._post("list", {"config": self._cfg()})
        self.assertEqual(resp.status_code, 413)


if __name__ == "__main__":
    unittest.main()
