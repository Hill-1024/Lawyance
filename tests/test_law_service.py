"""Run against the real HTTP listener with isolated keys, audit and a tiny corpus."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from law_service.server import (
    APIError, AuditLog, CANARY_QUERY, KeyPolicy, RateLimiter, ServiceState, create_server,
)


class FakeBackend:
    def get_engine(self):
        return self

    def read_cached_manifest(self):
        return {"schema_version": 5, "file_count": 1, "content_sha256": "abc", "total_size": 100}

    def law_exact_search(self, title, number):
        return json.dumps({"success": True, "data": {"law_name": title, "article_number": number,
                                                   "content": "法律条款"}}, ensure_ascii=False)

    def law_fuzzy_search(self, query, limit):
        return json.dumps({"success": True, "data": [{"content": query}], "returned_count": 1}, ensure_ascii=False)

    def law_link_search(self, text, limit):
        return json.dumps({"success": True, "references": [{"title": text}], "text": "信源"}, ensure_ascii=False)


class LawServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.keys = self.root / "keys.json"
        self.token = "lvk_test_customer_secret"
        self.policy = {"key": self.token, "name": "customer-a", "enabled": True,
                       "rpm": 1000, "daily_quota": 20000}
        self.write_keys([self.policy])
        self.state = ServiceState(self.keys, self.root / "audit.jsonl", backend=FakeBackend())
        self.state.initialize()
        self.server = create_server(("127.0.0.1", 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.state.audit.close()
        self.tmp.cleanup()

    def write_keys(self, policies):
        temporary = self.root / "keys-new.json"
        temporary.write_text(json.dumps({"keys": policies}), encoding="utf-8")
        os.replace(temporary, self.keys)

    def request(self, path, payload=None, *, key=True, method=None, headers=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {"Authorization": "Bearer " + self.token} if key else {}
        body = None if payload is None else payload if raw else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        conn.request(method or ("GET" if payload is None else "POST"), path, body, request_headers)
        response = conn.getresponse()
        content = response.read()
        status, response_headers = response.status, dict(response.getheaders())
        conn.close()
        return status, json.loads(content) if content else None, response_headers

    def wire(self, request):
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as conn:
            conn.sendall(request)
            data = bytearray()
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
        return bytes(data)

    def test_three_endpoints_preserve_engine_response(self):
        cases = [("exact", {"title": "测试法", "number": "第一条"}),
                 ("search", {"query": "赔偿", "limit": 20}),
                 ("links", {"text": "测试法第一条", "limit": 3})]
        for endpoint, payload in cases:
            status, data, headers = self.request("/v1/laws/" + endpoint, payload)
            self.assertEqual(status, 200)
            self.assertTrue(data["success"])
            self.assertEqual(headers["Cache-Control"], "no-store")
            if endpoint == "exact":
                self.assertEqual(data, json.loads(self.state.backend.law_exact_search("测试法", "第一条")))
            elif endpoint == "search":
                self.assertEqual(data, json.loads(self.state.backend.law_fuzzy_search("赔偿", 20)))
            else:
                self.assertEqual(data, json.loads(self.state.backend.law_link_search("测试法第一条", 3)))

    def test_auth_revocation_rotation_and_bad_config_fail_closed(self):
        self.assertEqual(self.request("/v1/meta", key=False)[0], 401)
        self.assertEqual(self.request("/v1/meta", headers={"Authorization": "Bearer lvk_unknown"})[0], 401)
        self.assertEqual(self.request("/v1/meta")[0], 200)
        self.policy["enabled"] = False
        self.write_keys([self.policy])
        self.assertEqual(self.request("/v1/meta")[0], 403)
        self.policy.update(enabled=True, key="lvk_rotated_customer_secret")
        self.write_keys([self.policy])
        self.assertEqual(self.request("/v1/meta")[0], 401)
        self.token = self.policy["key"]
        self.assertEqual(self.request("/v1/meta")[0], 200)
        self.keys.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.request("/v1/meta")[0], 503)
        self.write_keys([self.policy])
        self.assertEqual(self.request("/v1/meta")[0], 200)
        self.keys.unlink()
        self.assertEqual(self.request("/v1/meta")[0], 503)

    def test_disabled_key_and_queries_do_not_leak_in_audit(self):
        query = "秘密客户案情以及手机号13999990000"
        self.request("/v1/laws/search", {"query": query})
        self.request("/v1/meta?secret=" + self.token)
        self.policy["enabled"] = False
        self.write_keys([self.policy])
        self.request("/v1/meta")
        contents = (self.root / "audit.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(query, contents)
        self.assertNotIn(self.token, contents)
        events = [json.loads(line) for line in contents.splitlines()]
        event = events[0]
        self.assertEqual(event["query_sha256"], hashlib.sha256(query.encode()).hexdigest())
        self.assertEqual(event["query_length"], len(query))
        self.assertEqual(event["result_count"], 1)
        self.assertEqual(events[-1]["key_name"], "customer-a")
        self.assertEqual(events[-1]["status"], 403)
        self.assertEqual(set(event), {"timestamp", "key_name", "endpoint", "query_length", "query_sha256",
                                      "duration_ms", "status", "result_count", "ip"})

    def test_limits_are_per_key_and_return_retry_after(self):
        self.policy["rpm"] = 1
        other = dict(self.policy, key="lvk_another_test_customer", name="customer-b")
        self.write_keys([self.policy, other])
        self.assertEqual(self.request("/v1/meta")[0], 200)
        status, _, headers = self.request("/v1/meta")
        self.assertEqual(status, 429)
        self.assertGreater(int(headers["Retry-After"]), 0)
        self.token = other["key"]
        self.assertEqual(self.request("/v1/meta")[0], 200)

    def test_readiness_and_meta_visibility(self):
        self.assertEqual(self.request("/healthz", key=False)[:2], (200, {"ready": True}))
        self.assertEqual(self.request("/v1/meta")[1]["content_sha256"], "abc")
        self.state.ready = False
        self.assertEqual(self.request("/healthz", key=False)[:2], (503, {"ready": False}))
        self.assertEqual(self.request("/v1/meta")[0], 503)
        self.assertEqual(self.request("/v1/laws/search", {"query": "测试"})[0], 503)
        self.state.backend.get_engine = lambda: (_ for _ in ()).throw(ValueError("private-data"))
        self.state.initialize()
        self.assertFalse(self.state.ready)
        self.state.backend = FakeBackend()
        self.state.initialize()
        self.assertTrue(self.state.ready)

    def test_input_limits_and_content_types(self):
        cases = [("exact", {"title": "", "number": "第一条"}),
                 ("exact", {"title": "法" * 161, "number": "第一条"}),
                 ("exact", {"title": "测试法", "number": "条" * 41}),
                 ("search", {"query": " "}), ("search", {"query": "字" * 4001}),
                 ("links", {"text": "\0"}), ("links", {"text": 1}),
                 ("search", {"query": "字", "limit": True}),
                 ("search", {"query": "字", "limit": 21}),
                 ("search", {"query": "字", "limit": 0}),
                 ("search", {"query": "字", "offset": 10}), ("search", [])]
        for path, payload in cases:
            self.assertEqual(self.request("/v1/laws/" + path, payload)[0], 400, (path, payload))
        self.assertEqual(self.request("/v1/laws/search", b'{"query":"a","query":"b"}', raw=True)[0], 400)
        self.assertEqual(self.request("/v1/laws/search", b'\xff', raw=True)[0], 400)
        self.assertEqual(self.request("/v1/laws/search", b'{"query":"\\ud800"}', raw=True)[0], 400)
        self.assertEqual(self.request("/v1/laws/search", b"[" * 1500 + b"]" * 1500, raw=True)[0], 400)
        self.assertEqual(self.request("/v1/laws/search", {"query": "x"}, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/v1/laws/search", b" " * 65537, raw=True)[0], 413)
        self.assertEqual(self.request("/v1/laws/search")[0], 405)
        self.assertEqual(self.request("/v1/meta", {"x": "y"})[0], 405)
        self.assertEqual(self.request("/export")[0], 404)

    def test_connection_limit_rejects_excess_incomplete_clients(self):
        server = create_server(("127.0.0.1", 0), self.state, max_connections=1)
        accepted = threading.Event()
        original_worker = server.process_request_thread
        def track_connection(request, address):
            accepted.set()
            original_worker(request, address)
        server.process_request_thread = track_connection
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        occupied = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
        try:
            occupied.sendall(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n")
            self.assertTrue(accepted.wait(2))
            with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as extra:
                extra.sendall(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n")
                self.assertTrue(extra.recv(4096).startswith(b"HTTP/1.1 503 "))
        finally:
            occupied.close()
            server.shutdown()
            server.server_close()
            worker.join()

    def test_audit_write_failure_prevents_corpus_disclosure(self):
        handler = self.state.audit._handler
        with patch.object(handler, "shouldRollover", side_effect=OSError("private-path-disk-full")):
            status, data, _ = self.request("/v1/laws/search", {"query": "敏感查询"})
            self.assertEqual(status, 503)
            self.assertEqual(data, {"success": False, "message": "Audit log unavailable"})
            self.assertEqual(self.request("/healthz", key=False)[:2], (503, {"ready": False}))
        self.assertEqual(self.request("/v1/laws/search", {"query": "敏感查询"})[0], 200)

    def test_header_limits_and_duplicate_auth_are_rejected(self):
        cases = [(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\nCookie: " + b"x" * 65536 + b"\r\n\r\n", 431),
                 (b"GET /healthz HTTP/1.1\r\n" + b"X-Header: x\r\n" * 101 + b"\r\n", 431),
                 (b"GET /v1/meta HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer lvk_test_customer_secret\r\nAuthorization: Bearer lvk_test_customer_secret\r\n\r\n", 401)]
        for request, expected in cases:
            response = self.wire(request)
            self.assertTrue(response.startswith(("HTTP/1.1 %d " % expected).encode()), response)
            self.assertNotIn(self.token.encode(), response)

    def test_rejects_ambiguous_http_framing_and_expect(self):
        base = b"POST /v1/laws/search HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer lvk_test_customer_secret\r\n"
        for headers, expected in [(b"Transfer-Encoding: chunked\r\nContent-Length: 3\r\n", 400),
                                  (b"Content-Length: 3\r\nContent-Length: 3\r\n", 400),
                                  (b"Content-Type: application/json\r\n", 411),
                                  (b"Content-Length: -1\r\n", 411),
                                  (b"Expect: 100-continue\r\nContent-Length: 3\r\n", 417),
                                  (b"Content-Length: 999999999\r\n", 413)]:
            wire = self.wire(base + headers + b"\r\n{} ")
            self.assertTrue(wire.startswith(("HTTP/1.1 %d " % expected).encode()), wire)
            self.assertIn(b"Connection: close", wire)
            self.assertNotIn(b"100 Continue", wire)

    def test_canary_is_opt_in_and_requires_exact_diagnostic_query(self):
        payload = {"query": CANARY_QUERY}
        self.assertEqual(self.request("/v1/laws/search", payload)[1]["data"], [])
        self.policy["canary"] = True
        self.write_keys([self.policy])
        data = self.request("/v1/laws/search", payload)[1]
        self.assertTrue(data["canary"])
        marker = data["data"][0]["content"]
        self.assertTrue(marker.startswith("CANARY:"))
        self.assertNotIn(self.token, marker)
        ordinary = self.request("/v1/laws/search", {"query": "赔偿"})[1]
        self.assertNotIn("canary", ordinary)
        other = dict(self.policy, key="lvk_different_diagnostic_customer", name="diagnostic-b")
        self.write_keys([other])
        self.token = other["key"]
        self.assertNotEqual(self.request("/v1/laws/search", payload)[1]["data"][0]["content"], marker)


class RateLimiterTests(unittest.TestCase):
    def test_sliding_window_utc_day_reset_and_policy_changes(self):
        now = [86339.0]
        limiter = RateLimiter(clock=lambda: now[0])
        policy = KeyPolicy("hash", "a", True, 1, 2)
        limiter.check(policy)
        with self.assertRaises(APIError) as limited:
            limiter.check(policy)
        self.assertEqual(limited.exception.status, 429)
        now[0] += 60
        limiter.check(policy)
        with self.assertRaisesRegex(APIError, "Daily quota"):
            limiter.check(policy)
        now[0] = 86460
        limiter.check(policy)

    def test_concurrent_requests_cannot_exceed_quota(self):
        limiter = RateLimiter()
        policy = KeyPolicy("hash", "a", True, 100, 5)
        results = []
        def hit():
            try:
                limiter.check(policy)
                results.append(200)
            except APIError as exc:
                results.append(exc.status)
        threads = [threading.Thread(target=hit) for _ in range(25)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(200), 5)
        self.assertEqual(results.count(429), 20)

    def test_deleted_keys_are_removed_without_resetting_active_usage(self):
        limiter = RateLimiter()
        first = KeyPolicy("first", "a", True, 1, 5)
        second = KeyPolicy("second", "b", True, 1, 5)
        limiter.check(first)
        limiter.check(second)
        limiter.discard_removed(frozenset({second.fingerprint}))
        self.assertNotIn(first.fingerprint, limiter._usage)
        with self.assertRaises(APIError):
            limiter.check(second)

    def test_audit_log_rotates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            audit = AuditLog(path, max_bytes=64, backups=2)
            for i in range(10):
                audit.record(status=200, count=i, padding="x" * 20)
            audit.close()
            self.assertTrue(path.exists())
            self.assertTrue(path.with_name("audit.jsonl.1").exists())
            self.assertFalse(path.with_name("audit.jsonl.3").exists())


class PathEnvironmentTests(unittest.TestCase):
    def test_engine_uses_configured_data_database_and_manifest_paths(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LAW_DATA_DIR=str(Path(tmp) / "private"),
                       LAW_DB_PATH=str(Path(tmp) / "index" / "law.db"),
                       LAW_MANIFEST_PATH=str(Path(tmp) / "version" / "manifest.json"))
            script = "import json; from RAG import law_data_search as l; print(json.dumps([str(l.RAW_DATA_DIR),str(l.DB_PATH),str(l.MANIFEST_PATH)]))"
            output = subprocess.check_output([sys.executable, "-c", script], cwd=root, env=env, text=True)
            self.assertEqual(json.loads(output), [env["LAW_DATA_DIR"], env["LAW_DB_PATH"], env["LAW_MANIFEST_PATH"]])

    def test_links_limit_bounds_quoted_reference_results(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data" / "法律"
            data.mkdir(parents=True)
            source = {"law_name": "测试法", "short_name": "测试法", "effectiveness": "现行有效",
                      "url": "https://example.test/law", "articles": {
                          "第%d条" % i: "第%d条引用上限验证。" % i for i in range(1, 26)}}
            (data / "test.json").write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ, LAW_DATA_DIR=str(data.parent), LAW_DB_PATH=str(Path(tmp) / "law.db"),
                       LAW_MANIFEST_PATH=str(Path(tmp) / "manifest.json"))
            script = ("import json; from RAG import law_data_search as l; "
                      "q=' '.join('《测试法》第%d条'%i for i in range(1,26)); "
                      "r=json.loads(l.law_link_search(q,20)); print(len(r['references']))")
            count = subprocess.check_output([sys.executable, "-c", script], cwd=root, env=env, text=True)
            self.assertEqual(int(count.strip()), 20)


if __name__ == "__main__":
    unittest.main()
