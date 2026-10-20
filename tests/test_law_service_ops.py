import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("law_service_ops", Path(__file__).resolve().parents[1] / "scripts/law_service_ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class LawServiceOpsTests(unittest.TestCase):
    def event(self, **changes):
        return {"timestamp": datetime.now(timezone.utc).isoformat(), "key_name": "customer-a", "endpoint": "/v1/laws/search", "status": 200, "duration_ms": 12, "query_sha256": "a" * 64, "query_length": 4, **changes}

    def test_report_reads_rotation_filters_old_events_and_does_not_copy_private_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = Path(folder) / "audit.jsonl"
            audit.write_text(json.dumps(self.event(query="private case details")) + "\nmalformed\n", encoding="utf-8")
            audit.with_suffix(".jsonl.1").write_text(json.dumps(self.event(status=429)) + "\n" + json.dumps(self.event(timestamp=(datetime.now(timezone.utc) - timedelta(days=9)).isoformat())) + "\n", encoding="utf-8")
            events, invalid = ops.read_events(audit, datetime.now(timezone.utc) - timedelta(days=7))
            report = ops.summarize(events, invalid)
            self.assertEqual(report["requests"], 2)
            self.assertEqual(report["invalid_lines"], 1)
            self.assertEqual(report["keys"]["customer-a"]["rate_limited"], 1)
            self.assertNotIn("private case", json.dumps(report))

    def test_alerts_detect_failure_latency_and_abnormal_pattern(self):
        rows = [self.event(status=503, duration_ms=3000, query_sha256=str(i)) for i in range(100)]
        alerts = ops.alerts_for(ops.summarize(rows), p95_ms=2000, max_rpm=30, min_sample=100)
        self.assertEqual({row["kind"] for row in alerts}, {"server_errors", "latency_p95", "rate_pressure", "query_pattern"})

    def test_health_only_traffic_has_no_requests_keys_or_traffic_alerts(self):
        rows = [self.event(endpoint="/healthz", key_name=None, status=503,
                           duration_ms=9999, query_length=0) for _ in range(100)]
        summary = ops.summarize(rows)
        self.assertEqual(summary, {"requests": 0, "invalid_lines": 0, "keys": {}})
        self.assertEqual(ops.alerts_for(summary, p95_ms=1, max_rpm=1, min_sample=1), [])

    def test_current_and_rotated_health_probes_do_not_affect_business_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = Path(folder) / "audit.jsonl"
            timestamp = datetime.now(timezone.utc).isoformat()
            business = [self.event(timestamp=timestamp, duration_ms=10),
                        self.event(timestamp=timestamp, duration_ms=20, query_sha256="b" * 64)]
            auth_failures = [self.event(timestamp=timestamp, key_name=None, endpoint="/v1/meta", status=401, query_length=0),
                             self.event(timestamp=timestamp, key_name=None, endpoint="/unknown", status=403, query_length=0)]
            probes = [self.event(timestamp=timestamp, endpoint="/healthz", key_name=None,
                                 duration_ms=9999, status=503, query_length=0) for _ in range(100)]
            audit.write_text("".join(json.dumps(row) + "\n" for row in [business[0], auth_failures[0], *probes[:50]]), encoding="utf-8")
            audit.with_suffix(".jsonl.1").write_text("".join(json.dumps(row) + "\n" for row in [business[1], auth_failures[1], *probes[50:]]), encoding="utf-8")
            events, invalid = ops.read_events(audit, datetime.now(timezone.utc) - timedelta(days=7))
            self.assertEqual((len(events), invalid), (104, 0))
            summary = ops.summarize(events, invalid)
            self.assertEqual(summary["requests"], 4)
            customer = summary["keys"]["customer-a"]
            self.assertEqual(customer["requests"], 2)
            self.assertEqual(customer["p95_ms"], 20)
            self.assertEqual(customer["peak_rpm"], 2)
            self.assertEqual(customer["statuses"], {"200": 2})
            self.assertEqual(customer["unique_queries"], 2)
            unauthenticated = summary["keys"]["unauthenticated"]
            self.assertEqual(unauthenticated["requests"], 2)
            self.assertEqual(unauthenticated["statuses"], {"401": 1, "403": 1})
            self.assertEqual(unauthenticated["endpoints"], {"/unknown": 1, "/v1/meta": 1})
            self.assertEqual(ops.alerts_for(summary, p95_ms=100, max_rpm=3, min_sample=3), [])

    def test_only_exact_health_endpoint_is_excluded(self):
        summary = ops.summarize([self.event(endpoint=endpoint) for endpoint in
                                 ("/healthz", "/healthz/", "/healthz?ready=true")])
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["keys"]["customer-a"]["endpoints"],
                         {"/healthz/": 1, "/healthz?ready=true": 1})

    def test_health_only_cli_report_and_check_still_report_probe_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = Path(folder) / "audit.jsonl"
            audit.write_text(json.dumps(self.event(endpoint="/healthz", key_name=None,
                                                   status=503, duration_ms=9999, query_length=0)) + "\n", encoding="utf-8")
            with patch.object(ops, "probe") as probe, patch("builtins.print") as output:
                self.assertEqual(ops.main(["report", "--audit", str(audit)]), 0)
                self.assertEqual(json.loads(output.call_args.args[0])["requests"], 0)
                probe.assert_not_called()
            for available, expected in ((True, []), (False, [{"kind": "unavailable"}])):
                with self.subTest(available=available):
                    with patch.dict(ops.os.environ, {"LAW_MONITOR_KEY": "fixture-monitor"}), patch.object(ops, "probe", return_value=available), patch("builtins.print") as output:
                        self.assertEqual(ops.main(["check", "--audit", str(audit)]), int(not available))
                        summary = json.loads(output.call_args.args[0])
                    self.assertEqual(summary["requests"], 0)
                    self.assertEqual(summary["keys"], {})
                    self.assertEqual(summary["alerts"], expected)

    def test_malformed_health_rows_still_raise_audit_alerts(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = Path(folder) / "audit.jsonl"
            rows = [self.event(endpoint="/healthz", key_name=None, query_length=0),
                    self.event(endpoint="/healthz", query_sha256=[])]
            audit.write_text("".join(json.dumps(row) + "\n" for row in rows) + "malformed\n", encoding="utf-8")
            events, invalid = ops.read_events(audit, datetime.now(timezone.utc) - timedelta(days=7))
            self.assertEqual((len(events), invalid), (1, 2))
            summary = ops.summarize(events, invalid)
            self.assertEqual(summary, {"requests": 0, "invalid_lines": 2, "keys": {}})
            self.assertEqual(ops.alerts_for(summary, p95_ms=1, max_rpm=1, min_sample=1),
                             [{"kind": "audit_invalid", "count": 2}])
            with patch.dict(ops.os.environ, {"LAW_MONITOR_KEY": "fixture-monitor"}), patch.object(ops, "probe", return_value=True), patch("builtins.print") as output:
                self.assertEqual(ops.main(["check", "--audit", str(audit)]), 1)
                self.assertEqual(json.loads(output.call_args.args[0])["alerts"], [{"kind": "audit_invalid", "count": 2}])

    def test_quiet_check_recovers_without_client_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = Path(folder) / "audit.jsonl"
            audit.write_text(json.dumps(self.event()) + "\n", encoding="utf-8")
            with patch.dict(ops.os.environ, {"LAW_MONITOR_KEY": "lvk_monitor_test"}), patch.object(ops, "probe", return_value=False), patch("builtins.print"):
                self.assertEqual(ops.main(["check", "--audit", str(audit)]), 1)
            with patch.dict(ops.os.environ, {"LAW_MONITOR_KEY": "lvk_monitor_test"}), patch.object(ops, "probe", return_value=True), patch("builtins.print"):
                self.assertEqual(ops.main(["check", "--audit", str(audit)]), 0)

    def test_bad_hash_is_counted_and_missing_monitor_key_is_an_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            audit = Path(folder) / "audit.jsonl"
            audit.write_text(json.dumps(self.event(query_sha256=[])) + "\n", encoding="utf-8")
            events, invalid = ops.read_events(audit, datetime(2000, 1, 1, tzinfo=timezone.utc))
            self.assertEqual((events, invalid), ([], 1))
            with patch.dict(ops.os.environ, {"LAW_MONITOR_KEY": ""}), patch.object(ops, "probe") as probe, patch("builtins.print") as output:
                self.assertEqual(ops.main(["check", "--audit", str(audit)]), 1)
                self.assertIn("monitor_key_missing", output.call_args.args[0])
                probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
