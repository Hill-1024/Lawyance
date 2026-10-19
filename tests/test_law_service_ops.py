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
