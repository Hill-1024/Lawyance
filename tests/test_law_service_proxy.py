"""Proxy isolation with synthetic credentials and loopback-only HTTP listeners."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest import mock

import pytest
import requests

from mcp import law_service_client


ROOT = Path(__file__).resolve().parents[1]
KEY = "lvk_synthetic_proxy_regression_only"
ARTICLE = {"law_name": "Fixture Law", "article_number": "1", "content": "Fixture article", "url": "https://example.test/law/1"}


@pytest.fixture
def endpoints():
    service_calls, proxy_calls, servers, threads = [], [], [], []

    def start(calls, *, proxy=False):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                calls.append((self.path, self.headers.get("Authorization")))
                if proxy:
                    status, payload = 502, {"success": False}
                elif self.path.endswith("/links"):
                    status, payload = 200, {"success": True, "text": "Fixture source"}
                else:
                    status, payload = 200, {"success": True, "data": [ARTICLE] if self.path.endswith("/search") else ARTICLE}
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        servers.append(server)
        threads.append(thread)
        thread.start()
        return f"http://127.0.0.1:{server.server_port}"

    service_url, proxy_url = start(service_calls), start(proxy_calls, proxy=True)
    environment = {
        "HTTP_PROXY": proxy_url, "http_proxy": proxy_url,
        "HTTPS_PROXY": proxy_url, "https_proxy": proxy_url,
        "ALL_PROXY": proxy_url, "all_proxy": proxy_url,
        "NO_PROXY": "", "no_proxy": "",
        "LAWVER_LAW_SOURCE": "remote", "LAWVER_LAW_SERVICE_URL": service_url,
        "LAWVER_LAW_SERVICE_KEY": KEY, "LAWVER_LAW_SERVICE_TIMEOUT": "2",
    }
    try:
        yield environment, service_calls, proxy_calls
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


def test_all_three_requests_stay_local_despite_environment_proxies(endpoints):
    environment, service_calls, proxy_calls = endpoints
    with mock.patch.dict(os.environ, environment):
        results = [
            law_service_client.law_exact_search("Fixture Law", "1"),
            law_service_client.law_fuzzy_search("fixture"),
            law_service_client.law_link_search("Fixture Law 1"),
        ]
    assert all(json.loads(result)["success"] for result in results)
    assert [path for path, _ in service_calls] == ["/v1/laws/exact", "/v1/laws/search", "/v1/laws/links"]
    assert all(authorization == f"Bearer {KEY}" for _, authorization in service_calls)
    assert proxy_calls == []


def test_https_transport_keeps_tls_validation_and_ignores_proxy_netrc_and_ca_env(tmp_path):
    netrc = tmp_path / "fixture.netrc"
    netrc.write_text("machine law.example.test login fixture-user password fixture-password\n", encoding="utf-8")
    netrc.chmod(0o600)
    snapshots = []

    def send(adapter, request, **settings):
        snapshots.append((request, settings))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"success": True, "text": "Fixture source"}).encode()
        response._content_consumed = True
        response.request, response.url = request, request.url
        return response

    environment = {
        "LAWVER_LAW_SOURCE": "remote", "LAWVER_LAW_SERVICE_URL": "https://law.example.test",
        "LAWVER_LAW_SERVICE_KEY": KEY, "LAWVER_LAW_SERVICE_TIMEOUT": "2",
        "HTTP_PROXY": "http://proxy.invalid:1", "http_proxy": "http://proxy.invalid:1",
        "HTTPS_PROXY": "http://proxy.invalid:1", "https_proxy": "http://proxy.invalid:1",
        "ALL_PROXY": "http://proxy.invalid:1", "all_proxy": "http://proxy.invalid:1",
        "NO_PROXY": "", "no_proxy": "", "NETRC": str(netrc),
        "REQUESTS_CA_BUNDLE": str(tmp_path / "not-a-ca-bundle"),
        "CURL_CA_BUNDLE": str(tmp_path / "also-not-a-ca-bundle"),
    }
    with mock.patch.dict(os.environ, environment), mock.patch.object(
        requests.adapters.HTTPAdapter, "send", autospec=True, side_effect=send,
    ):
        assert json.loads(law_service_client.law_link_search("Fixture Law 1"))["success"]
    assert len(snapshots) == 1
    request, settings = snapshots[0]
    assert request.url == "https://law.example.test/v1/laws/links"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert settings["proxies"] == {}
    assert settings["verify"] is True
    assert settings["timeout"] == (2.0, 2.0)


def test_configuration_probe_accepts_other_clients_proxy_settings(endpoints, tmp_path):
    settings, service_calls, proxy_calls = endpoints
    spec = importlib.util.spec_from_file_location("proxy_test_prepare", ROOT / "scripts/deploy/prepare_law_remote.py")
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    candidate = tmp_path / "candidate.env"
    candidate.write_text("".join(f"{name}={value}\n" for name, value in settings.items() if name.startswith("LAWVER_")), encoding="utf-8")
    environment = {
        name: value for name, value in os.environ.items()
        if name.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"}
    }
    environment.update({name: value for name, value in settings.items() if not name.startswith("LAWVER_")})
    environment.update(PYTHONIOENCODING="utf-8", LAWVER_RELEASE_SYNC_ON_STARTUP="0")
    completed = subprocess.run(
        [sys.executable, "-B", "-c", prepare.PROBE, str(candidate)], cwd=ROOT,
        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count("PASS CN remote tool:") == 3
    assert len(service_calls) == 3
    assert all(authorization == f"Bearer {KEY}" for _, authorization in service_calls)
    assert proxy_calls == []
