"""Loopback HTTP API for the private legal corpus.

The reverse proxy/tunnel terminates TLS. Never expose this standard-library HTTP
listener directly to the Internet. No query or credential is written to logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import socket
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path


CANARY_QUERY = "__lawver_canary__"
MAX_BODY_BYTES = 65536
MAX_QUERY_CHARS = 4000
MAX_TITLE_CHARS = 160
MAX_NUMBER_CHARS = 40
MAX_LIMIT = 20
BUSINESS_PATHS = frozenset(("/v1/laws/exact", "/v1/laws/search", "/v1/laws/links"))
KNOWN_PATHS = BUSINESS_PATHS | {"/v1/meta", "/healthz"}


class APIError(Exception):
    def __init__(self, status: int, message: str, retry_after: int = 0):
        self.status = status
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)


@dataclass(frozen=True)
class KeyPolicy:
    fingerprint: str
    name: str
    enabled: bool
    rpm: int
    daily_quota: int
    canary: bool = False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError("invalid JSON number")


def _read_json(value):
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant)


class KeyStore:
    """Reload atomically replaced key files and fail closed on invalid updates."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._signature = None
        self._policies = {}
        self._valid = False
        self._lock = threading.Lock()

    def fingerprints(self):
        with self._lock:
            return frozenset(self._policies)

    def authenticate(self, authorization: str) -> KeyPolicy:
        with self._lock:
            try:
                stat = self.path.stat()
                signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
                if signature != self._signature:
                    self._signature = signature
                    self._policies = {}
                    self._valid = False
                    if stat.st_size > 1024 * 1024:
                        raise ValueError("key configuration too large")
                    data = _read_json(self.path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
                        raise ValueError("invalid key configuration")
                    policies = {}
                    for item in data["keys"]:
                        if not isinstance(item, dict):
                            raise ValueError("invalid key policy")
                        key = item.get("key")
                        name = item.get("name")
                        if not isinstance(key, str) or not re.fullmatch(r"lvk_[A-Za-z0-9_-]{4,256}", key):
                            raise ValueError("invalid key")
                        if not isinstance(name, str) or not name.strip() or len(name) > 128:
                            raise ValueError("invalid key name")
                        name.encode("utf-8")
                        enabled = item.get("enabled", True)
                        canary = item.get("canary", False)
                        if type(enabled) is not bool or type(canary) is not bool:
                            raise ValueError("invalid key flags")
                        rpm, quota = item.get("rpm", 30), item.get("daily_quota", 20000)
                        if type(rpm) is not int or type(quota) is not int or not (1 <= rpm <= 100000 and 1 <= quota <= 100000000):
                            raise ValueError("invalid key limits")
                        fingerprint = hashlib.sha256(key.encode("ascii")).hexdigest()
                        if fingerprint in policies:
                            raise ValueError("duplicate key")
                        policies[fingerprint] = KeyPolicy(fingerprint, name, enabled, rpm, quota, canary)
                    self._policies, self._valid = policies, True
            except (OSError, ValueError, UnicodeError):
                self._signature = None
                self._policies, self._valid = {}, False
            if not self._valid:
                raise APIError(503, "Key configuration unavailable", 30)
            if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                raise APIError(401, "Invalid API key")
            token = authorization[7:]
            if not re.fullmatch(r"lvk_[A-Za-z0-9_-]{4,256}", token):
                raise APIError(401, "Invalid API key")
            policy = self._policies.get(hashlib.sha256(token.encode("ascii")).hexdigest())
            if policy is None:
                raise APIError(401, "Invalid API key")
            if not policy.enabled:
                error = APIError(403, "API key disabled")
                error.key_name = policy.name
                raise error
            return policy


class RateLimiter:
    """Per-process rolling minute and UTC calendar-day quotas, shared by threads."""

    def __init__(self, enabled=True, clock=time.time):
        self.enabled = enabled
        self.clock = clock
        self._usage = {}
        self._lock = threading.Lock()

    def discard_removed(self, active):
        with self._lock:
            for fingerprint in self._usage.keys() - active:
                del self._usage[fingerprint]

    def check(self, policy: KeyPolicy):
        if not self.enabled:
            return
        now = self.clock()
        day = int(now // 86400)
        with self._lock:
            window, saved_day, count = self._usage.get(policy.fingerprint, (deque(), day, 0))
            if saved_day != day:
                count = 0
            while window and window[0] <= now - 60:
                window.popleft()
            self._usage[policy.fingerprint] = (window, day, count)
            if count >= policy.daily_quota:
                raise APIError(429, "Daily quota exceeded", max(1, math.ceil((day + 1) * 86400 - now)))
            if len(window) >= policy.rpm:
                raise APIError(429, "Rate limit exceeded", max(1, math.ceil(window[0] + 60 - now)))
            window.append(now)
            self._usage[policy.fingerprint] = (window, day, count + 1)


class _AuditHandler(RotatingFileHandler):
    def handleError(self, record):
        # logging normally swallows disk/rotation failures and prints the record.
        # A successful corpus response requires a durable audit write attempt.
        raise OSError("Audit log unavailable") from None


class AuditLog:
    def __init__(self, path: Path, max_bytes=10 * 1024 * 1024, backups=7):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.Logger("law-service-audit", logging.INFO)
        self._logger.propagate = False
        self._handler = _AuditHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        self._logger.addHandler(self._handler)

    def record(self, **fields):
        self._logger.info(json.dumps(fields, ensure_ascii=False, separators=(",", ":")))

    def close(self):
        self._handler.close()


class ServiceState:
    """Injectable backend supports isolated tests without a production corpus."""

    def __init__(self, keys_file: Path, audit_log: Path, *, backend=None, rate_limit_enabled=True):
        self.keys = KeyStore(keys_file)
        self.audit = AuditLog(audit_log)
        self.limiter = RateLimiter(rate_limit_enabled)
        self.backend = backend
        self.ready = False
        self.meta = {}
        self._initializing = threading.Lock()

    def initialize(self):
        # Failure leaves healthz at 503. Restart after fixing the corpus/paths.
        with self._initializing:
            self.ready = False
            try:
                if self.backend is None:
                    from RAG import law_data_search
                    self.backend = law_data_search
                self.backend.get_engine()
                manifest = self.backend.read_cached_manifest() or {}
                if not manifest.get("file_count"):
                    raise ValueError("empty corpus")
                self.meta = {name: manifest.get(name) for name in
                             ("schema_version", "file_count", "content_sha256", "total_size")}
                self.ready = True
            except Exception:
                # Avoid traceback: exceptions from the engine can contain queries,
                # source text or private paths. Readiness is the diagnostic signal.
                self.ready = False

    def invoke(self, path: str, payload: dict, policy: KeyPolicy) -> bytes:
        if path == "/v1/laws/search" and payload["query"] == CANARY_QUERY:
            marker = hmac.new(bytes.fromhex(policy.fingerprint), b"lawver-canary-v1", hashlib.sha256).hexdigest()[:24]
            data = []
            if policy.canary:
                data = [{"law_name": "法库诊断金丝雀（非真实法规）", "article_number": "诊断条目",
                         "content": "CANARY:" + marker, "category": "diagnostic", "url": "", "cli": ""}]
            result = {"success": bool(data), "message": "法库诊断结果（非法律检索结果）", "data": data,
                      "total_count": len(data), "returned_count": len(data), "canary": bool(data)}
            return json.dumps(result, ensure_ascii=False).encode("utf-8")
        if path == "/v1/laws/exact":
            raw = self.backend.law_exact_search(payload["title"], payload["number"])
        elif path == "/v1/laws/search":
            raw = self.backend.law_fuzzy_search(payload["query"], payload["limit"])
        else:
            raw = self.backend.law_link_search(payload["text"], payload["limit"])
        parsed = _read_json(raw)
        if not isinstance(parsed, dict):
            raise ValueError("invalid backend response")
        # Keep the engine JSON bytes unchanged: callers rely on its message/text shape.
        return raw.encode("utf-8") if isinstance(raw, str) else raw


def validate_payload(path, payload):
    if not isinstance(payload, dict):
        raise APIError(400, "JSON object required")
    fields = {"title": MAX_TITLE_CHARS, "number": MAX_NUMBER_CHARS} if path.endswith("/exact") else {
        "query" if path.endswith("/search") else "text": MAX_QUERY_CHARS}
    allowed = set(fields) | ({"limit"} if not path.endswith("/exact") else set())
    if set(payload) - allowed:
        raise APIError(400, "Unknown request fields")
    result = dict(payload)
    for field, max_chars in fields.items():
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > max_chars or "\x00" in value:
            raise APIError(400, "Invalid or overlong " + field)
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise APIError(400, "Invalid Unicode in " + field) from None
    if "limit" in allowed:
        limit = payload.get("limit", 5)
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            raise APIError(400, "limit must be an integer between 1 and 20")
        result["limit"] = limit
    return result


def _result_count(raw):
    data = _read_json(raw)
    for field in ("data", "references"):
        value = data.get(field)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return 1
    return 0


def _close_write_and_drain(connection):
    """Deliver rejections before closing sockets with unread request bodies.

    Closing a TCP socket with unread input can replace a queued HTTP response
    with a reset (especially on Windows). Half-close sends the response FIN,
    then give a well-behaved client a bounded chance to consume it and close.
    Both time and byte limits prevent slow or oversized clients retaining slots.
    """
    try:
        connection.shutdown(socket.SHUT_WR)
        deadline = time.monotonic() + 0.25
        remaining = MAX_BODY_BYTES * 4
        while remaining > 0:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            connection.settimeout(timeout)
            chunk = connection.recv(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
    except OSError:
        pass


class LawHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    request_queue_size = 32
    allow_reuse_address = True

    def __init__(self, address, state, *, max_connections=32):
        self.state = state
        self._slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, LawHandler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\nRetry-After: 1\r\n\r\n")
            except OSError:
                pass
            _close_write_and_drain(request)
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # The base implementation emits raw request context in tracebacks.
        pass


class LawHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LawService"
    sys_version = ""

    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def finish(self):
        try:
            super().finish()
        finally:
            _close_write_and_drain(self.connection)

    def log_message(self, format, *args):
        # BaseHTTPRequestHandler logs raw paths, including potential sensitive query strings.
        pass

    def send_error(self, code, message=None, explain=None):
        # Parser errors must also be JSON, never echo an untrusted request line.
        self._respond(code, {"success": False, "message": "Invalid HTTP request"})

    def handle_expect_100(self):
        self._respond(417, {"success": False, "message": "Expect is unsupported"})
        return False

    def _respond(self, status, payload, retry_after=0):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        if retry_after:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self._handle()

    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
    do_PATCH = do_GET
    do_OPTIONS = do_GET
    do_HEAD = do_GET

    def _dispatch(self, path, details):
        state = self.server.state
        if self.headers.get_all("Transfer-Encoding"):
            raise APIError(400, "Transfer-Encoding is unsupported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise APIError(400, "Duplicate Content-Length")
        if path == "unknown":
            raise APIError(404, "Unknown endpoint")
        if self.command != ("POST" if path in BUSINESS_PATHS else "GET"):
            raise APIError(405, "Method not allowed")
        if self.command == "GET" and lengths and lengths[0] != "0":
            raise APIError(400, "GET request body is unsupported")
        if path == "/healthz":
            return (200 if state.ready else 503), {"ready": state.ready}, 0
        auth_headers = self.headers.get_all("Authorization", [])
        if len(auth_headers) != 1:
            raise APIError(401, "Invalid API key")
        policy = state.keys.authenticate(auth_headers[0])
        details["key_name"] = policy.name
        state.limiter.discard_removed(state.keys.fingerprints())
        if self.command == "POST":
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
                raise APIError(411, "Content-Length required")
            length = int(lengths[0])
            if not 1 <= length <= MAX_BODY_BYTES:
                raise APIError(413, "Request body too large or empty")
            content_types = self.headers.get_all("Content-Type", [])
            if len(content_types) != 1 or content_types[0].split(";", 1)[0].strip().lower() != "application/json":
                raise APIError(415, "Content-Type must be application/json")
            if self.headers.get_all("Content-Encoding"):
                raise APIError(415, "Content-Encoding is unsupported")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise APIError(400, "Incomplete request body")
            try:
                payload = _read_json(raw.decode("utf-8"))
            except (UnicodeError, ValueError, RecursionError):
                raise APIError(400, "Invalid JSON") from None
            payload = validate_payload(path, payload)
            details["query"] = (payload["title"] + "\n" + payload["number"]) if path.endswith("/exact") else payload.get("query", payload.get("text", ""))
        state.limiter.check(policy)
        if not state.ready:
            raise APIError(503, "Law index unavailable", 5)
        if path == "/v1/meta":
            result = json.dumps(state.meta, ensure_ascii=False).encode("utf-8")
        else:
            result = state.invoke(path, payload, policy)
            details["result_count"] = _result_count(result)
        return 200, result, 0

    def _handle(self):
        started = time.monotonic()
        details = {"key_name": "", "query": "", "result_count": 0}
        path = self.path if self.path in KNOWN_PATHS else "unknown"
        retry_after = 0
        try:
            status, result, retry_after = self._dispatch(path, details)
        except APIError as exc:
            status = exc.status
            details["key_name"] = getattr(exc, "key_name", details["key_name"])
            result = {"success": False, "message": exc.message}
            retry_after = exc.retry_after
        except (TimeoutError, socket.timeout):
            status, result = 408, {"success": False, "message": "Request timed out"}
        except (ConnectionError, OSError, sqlite3.Error, ValueError):
            status, result = 503, {"success": False, "message": "Law service unavailable"}
            retry_after = 5
        except Exception:
            status, result = 500, {"success": False, "message": "Law service error"}
        if path == "/healthz":
            # Readiness probes return no corpus and must not pollute usage audit.
            # Monitor authenticated /v1/meta as well to detect key/audit failures.
            self._respond(status, result, retry_after)
            return
        try:
            self.server.state.audit.record(
                timestamp=datetime.now(timezone.utc).isoformat(), key_name=details["key_name"],
                endpoint=path, query_length=len(details["query"]),
                query_sha256=hashlib.sha256(details["query"].encode("utf-8")).hexdigest(),
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                status=status, result_count=details["result_count"], ip=self.client_address[0])
        except Exception:
            # Never disclose corpus content without its audit record. In particular,
            # rotating-file failures must not become silent successful responses.
            status = 503
            result = {"success": False, "message": "Audit log unavailable"}
            retry_after = 5
        self._respond(status, result, retry_after)


def create_server(address, state, **kwargs):
    return LawHTTPServer(address, state, **kwargs)


def main():
    listen = os.environ.get("LAW_LISTEN", "127.0.0.1:8084")
    host, separator, port = listen.rpartition(":")
    if not separator or not host or not port.isdigit():
        raise SystemExit("LAW_LISTEN must be host:port")
    state = ServiceState(Path(os.environ.get("LAW_KEYS_FILE", "keys.json")),
                         Path(os.environ.get("LAW_AUDIT_LOG", "logs/law-audit.jsonl")),
                         rate_limit_enabled=os.environ.get("LAW_RATE_LIMIT_ENABLED", "1") != "0")
    server = create_server((host, int(port)), state)
    threading.Thread(target=state.initialize, daemon=True, name="law-index-init").start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        state.audit.close()
