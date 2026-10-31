"""真实 SQLite 引擎 → HTTP 服务 → 主应用三工具与运维探针的对照验收。"""

import contextlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from RAG import law_data_search as engine
from law_service.server import ServiceState, create_server
from mcp import law_service_client, pkulaw_client
from scripts import law_service_ops as ops


class LawServiceEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        corpus, cache = folder / "corpus", folder / "cache"
        corpus.mkdir()
        (corpus / "test.json").write_text(json.dumps({
            "law_name": "中华人民共和国测试法", "short_name": "测试法",
            "url": "https://example.test/law/1", "effectiveness": "现行有效",
            "articles": {"第一条": "测试合同应当依法履行。", "第二条": "违反测试合同应当承担违约责任。"},
        }, ensure_ascii=False), encoding="utf-8")
        self.stack.enter_context(patch.multiple(engine, RAW_DATA_DIR=corpus, CACHE_DIR=cache, DB_PATH=cache / "law.db", MANIFEST_PATH=cache / "manifest.json", _ENGINE=None))
        self.key = "lvk_e2e_customer_test"
        self.canary = "lvk_e2e_diagnostic_test"
        self.key_file = folder / "keys.json"
        self.key_file.write_text(json.dumps({"keys": [
            {"key": self.key, "name": "customer-e2e", "rpm": 100, "daily_quota": 1000},
            {"key": self.canary, "name": "monitor-e2e", "rpm": 100, "daily_quota": 1000, "canary": True},
        ]}), encoding="utf-8")
        self.audit = folder / "audit.jsonl"
        self.state = ServiceState(self.key_file, self.audit, backend=engine)
        self.addCleanup(self.state.audit.close)
        self.state.initialize()
        self.assertTrue(self.state.ready)
        self.server = create_server(("127.0.0.1", 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.stack.enter_context(patch.dict(os.environ, {
            "LAWVER_LAW_SERVICE_URL": self.url, "LAWVER_LAW_SERVICE_KEY": self.key,
            "PKU_LAW_SOURCE": "remote", "NO_PROXY": "127.0.0.1,localhost",
        }))

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def test_real_http_and_local_outputs_match_for_all_three_tools(self):
        calls = [(pkulaw_client.get_article, ("测试法", "第一条")),
                 (pkulaw_client.search_article, ("测试合同",)),
                 (pkulaw_client.get_linked_content, ("《测试法》第一条",))]
        with patch.dict(os.environ, {"LAWVER_LAW_SOURCE": "local"}):
            local = [json.loads(function(*args)) for function, args in calls]
        self.assertTrue(all(row["success"] for row in local))
        with patch.dict(os.environ, {"LAWVER_LAW_SOURCE": "remote"}):
            with patch.object(pkulaw_client, "_local_search_engine", side_effect=AssertionError("remote imported RAG")):
                remote = [json.loads(function(*args)) for function, args in calls]
                self.assertEqual(pkulaw_client.ensure_law_database_ready()["mode"], "remote")
        self.assertEqual(remote, local)
        events, invalid = ops.read_events(self.audit, ops.datetime(2000, 1, 1, tzinfo=ops.timezone.utc))
        self.assertEqual(invalid, 0)
        self.assertEqual(len(events), 3)
        self.assertEqual({row["status"] for row in events}, {200})
        raw = self.audit.read_text(encoding="utf-8")
        for private in (self.key, "测试法", "测试合同", "《测试法》第一条"):
            self.assertNotIn(private, raw)

    def test_outage_recovery_and_canary_probe_without_customer_reconfiguration(self):
        self.assertTrue(ops.probe(self.url, self.key))
        self.assertFalse(ops.probe(self.url, ""))
        self.assertTrue(ops.probe_canary(self.url, self.canary))
        self.assertFalse(ops.probe_canary(self.url, self.key))
        self.assertFalse(ops.probe(self.url, "lvk_invalid_key"))
        with patch.dict(os.environ, {"LAWVER_LAW_SOURCE": "remote"}):
            self.state.ready = False
            self.assertFalse(ops.probe(self.url, self.key))
            failure = json.loads(pkulaw_client.get_article("测试法", "第一条"))
            self.assertFalse(failure["success"])
            self.assertIn("503", failure["message"])
            self.state.ready = True
            self.assertTrue(ops.probe(self.url, self.key))
            self.assertTrue(json.loads(pkulaw_client.get_article("测试法", "第一条"))["success"])
        saved = self.key_file.read_bytes()
        self.key_file.unlink()
        self.assertFalse(ops.probe(self.url, self.key))
        self.key_file.write_bytes(saved)
        self.assertTrue(ops.probe(self.url, self.key))

    def test_cited_links_honor_the_result_limit(self):
        result = json.loads(law_service_client.law_link_search("《测试法》第一条；《测试法》第二条", limit=1))
        self.assertTrue(result["success"])
        self.assertEqual(len(result["references"]), 1)

    def test_authenticated_monitor_detects_audit_failure_when_health_is_ready(self):
        self.assertTrue(ops.probe(self.url, self.key))
        handler = self.state.audit._handler
        with patch.object(handler, "shouldRollover", side_effect=OSError("fixture-audit-unavailable")):
            # The live /healthz check succeeds, but authenticated /v1/meta must fail.
            self.assertFalse(ops.probe(self.url, self.key))
        self.assertTrue(ops.probe(self.url, self.key))


if __name__ == "__main__":
    unittest.main()
