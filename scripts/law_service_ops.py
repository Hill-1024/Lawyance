"""法库审计周报与巡检；标准库实现，输出可交给现有监控收集。"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_events(audit: Path, since: datetime) -> tuple[list[dict], int]:
    """读取轮转文件；绝不把坏行或未认可字段输出进报告。"""
    events, invalid = [], 0
    for filename in sorted(audit.parent.glob(audit.name + "*")):
        if not filename.is_file() or (filename != audit and not filename.suffix[1:].isdigit()):
            continue
        with filename.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                    timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        raise ValueError("timezone required")
                    if not isinstance(event.get("duration_ms", 0), (float, int)) or not math.isfinite(event.get("duration_ms", 0)) or event.get("duration_ms", 0) < 0:
                        raise ValueError("invalid duration")
                    if type(event.get("query_length")) is not int or event["query_length"] < 0:
                        raise ValueError("invalid length")
                    if not isinstance(event.get("query_sha256"), str) or not re.fullmatch("[0-9a-f]{64}", event["query_sha256"]):
                        raise ValueError("invalid query hash")
                    if type(event.get("status")) is not int or not 100 <= event["status"] <= 599:
                        raise ValueError("invalid status")
                    if timestamp >= since:
                        events.append(event)
                except (ValueError, KeyError, TypeError, AttributeError):
                    invalid += 1
    return events, invalid


def summarize(events: list[dict], invalid: int = 0) -> dict:
    # Also exclude historical probes in current/rotated audit files. Validation
    # stays in read_events, so malformed health rows still raise audit alerts.
    events = [event for event in events if event.get("endpoint") != "/healthz"]
    grouped = defaultdict(list)
    for event in events:
        grouped[str(event.get("key_name") or "unauthenticated")].append(event)
    keys = {}
    for name, rows in sorted(grouped.items()):
        durations = sorted(float(row.get("duration_ms", 0)) for row in rows)
        statuses = Counter(str(row.get("status", 0)) for row in rows)
        hashes = {row.get("query_sha256") for row in rows if row.get("query_length", 0)}
        hashes.discard(None)
        minutes = Counter(str(row["timestamp"])[:16] for row in rows)
        keys[name] = {
            "requests": len(rows),
            "statuses": dict(sorted(statuses.items())),
            "errors_5xx": sum(count for status, count in statuses.items() if status.startswith("5")),
            "rate_limited": statuses.get("429", 0),
            "p95_ms": durations[max(0, math.ceil(len(durations) * .95) - 1)],
            "unique_queries": len(hashes),
            "unique_ratio": round(len(hashes) / len(rows), 3),
            "peak_rpm": max(minutes.values()),
            "endpoints": dict(sorted(Counter(str(row.get("endpoint", "")) for row in rows).items())),
        }
    return {"requests": len(events), "invalid_lines": invalid, "keys": keys}


def alerts_for(summary: dict, *, p95_ms: float, max_rpm: int, min_sample: int) -> list[dict]:
    alerts = []
    if summary["invalid_lines"]:
        alerts.append({"kind": "audit_invalid", "count": summary["invalid_lines"]})
    for name, usage in summary["keys"].items():
        kinds = []
        if usage["errors_5xx"]:
            kinds.append("server_errors")
        if usage["p95_ms"] > p95_ms:
            kinds.append("latency_p95")
        if usage["rate_limited"] or usage["peak_rpm"] >= max_rpm:
            kinds.append("rate_pressure")
        # 大量不同查询可能是遍历，大量重复查询也可能是客户端重试失控；均只告警供人工核查。
        if usage["requests"] >= min_sample and (usage["unique_ratio"] >= .95 or usage["unique_ratio"] <= .05):
            kinds.append("query_pattern")
        alerts.extend({"kind": kind, "key_name": name} for kind in kinds)
    return alerts


def probe(url: str, key: str) -> bool:
    if not key:
        return False
    try:
        request = Request(url.rstrip("/") + "/healthz", headers={"Authorization": "Bearer " + key})
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            payload = json.loads(response.read(65536))
            ready = response.status == 200 and isinstance(payload, dict) and (
                payload.get("ready") is True or payload.get("status") == "ok"
            )
        if ready and key:
            request = Request(url.rstrip("/") + "/v1/meta", headers={"Authorization": "Bearer " + key})
            with build_opener(NoRedirect).open(request, timeout=10) as response:
                payload = json.loads(response.read(65536))
                ready = response.status == 200 and isinstance(payload, dict) and bool(payload.get("content_sha256"))
        return ready
    except (OSError, ValueError, HTTPError, URLError):
        return False


def probe_canary(url: str, key: str) -> bool:
    if not key:
        return False
    try:
        request = Request(url.rstrip("/") + "/v1/laws/search", data=json.dumps({"query": "__lawver_canary__", "limit": 1}).encode(), headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            payload = json.loads(response.read(65536))
            return response.status == 200 and payload.get("canary") is True
    except (OSError, ValueError, HTTPError, URLError):
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("report", "check"))
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument("--url", default="http://127.0.0.1:8084")
    parser.add_argument("--key-env", default="LAW_MONITOR_KEY")
    parser.add_argument("--canary-key-env", help="可选：canary:true 的专用监控 key 所在环境变量")
    parser.add_argument("--p95-ms", type=float, default=2000)
    parser.add_argument("--max-rpm", type=int, default=30)
    parser.add_argument("--min-sample", type=int, default=100)
    args = parser.parse_args(argv)
    if min(args.days, args.minutes, args.max_rpm, args.min_sample, args.p95_ms) <= 0:
        parser.error("窗口和阈值必须大于零")
    parsed = urlsplit(args.url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("--url 必须是无凭据/查询/片段的 HTTP(S) 地址")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("远程探针必须使用 HTTPS，HTTP 仅允许回环地址")
    since = datetime.now(timezone.utc) - (
        timedelta(days=args.days) if args.command == "report" else timedelta(minutes=args.minutes)
    )
    if not args.audit.is_file():
        print(json.dumps({"alerts": [{"kind": "audit_missing"}]}))
        return 1
    events, invalid = read_events(args.audit, since)
    summary = summarize(events, invalid)
    summary["since"] = since.isoformat()
    if args.command == "check":
        alerts = alerts_for(summary, p95_ms=args.p95_ms, max_rpm=args.max_rpm, min_sample=args.min_sample)
        monitor_key = os.environ.get(args.key_env, "")
        if not monitor_key:
            alerts.append({"kind": "monitor_key_missing"})
        elif not probe(args.url, monitor_key):
            alerts.append({"kind": "unavailable"})
        if args.canary_key_env and not probe_canary(args.url, os.environ.get(args.canary_key_env, "")):
            alerts.append({"kind": "canary_failed"})
        summary["alerts"] = alerts
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary.get("alerts") else 0


if __name__ == "__main__":
    sys.exit(main())
