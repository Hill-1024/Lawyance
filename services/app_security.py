"""
模块描述：应用级 CORS、CSRF、限流和访问日志中间件。
"""

from collections import defaultdict
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse
import ipaddress
import logging
import os
import re
import time

from fastapi import Request, Response

from auth import verify_token


SECURE_ORIGIN = "https://law.mutsumi.moe"
NATIVE_CLIENT_ORIGINS = {"https://localhost", "capacitor://localhost"}
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_ORIGIN_RE = re.compile(r"^https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d+)?$")
RATE_LIMIT = 100


def _configured_usage_log_path() -> Path:
    explicit_path = os.getenv("LAWVER_USAGE_LOG_PATH")
    if explicit_path:
        return Path(explicit_path)
    return Path(os.getenv("LAWVER_DATA_DIR", "data")) / "usage.log"


def _configured_origins() -> set[str]:
    origins = {SECURE_ORIGIN, *NATIVE_CLIENT_ORIGINS}
    for raw_name in ("LAWVER_ALLOWED_ORIGINS", "ALLOWED_ORIGINS"):
        raw_value = os.getenv(raw_name, "")
        for item in raw_value.split(","):
            origin = item.strip().rstrip("/")
            if origin and origin != "*":
                origins.add(origin)
    return origins


ALLOWED_ORIGINS = sorted(_configured_origins())

configured_usage_log_path = _configured_usage_log_path()
configured_usage_log_path.parent.mkdir(parents=True, exist_ok=True)
usage_logger = logging.getLogger("usage_logger")
usage_logger.setLevel(logging.INFO)


def _install_usage_log_handler(log_path: Path) -> None:
    target = log_path.resolve()
    for handler in list(usage_logger.handlers):
        if not isinstance(handler, RotatingFileHandler):
            continue
        if Path(handler.baseFilename).resolve() == target:
            return
        usage_logger.removeHandler(handler)
        handler.close()

    file_handler = RotatingFileHandler(
        str(log_path),
        maxBytes=int(os.environ.get("LAWVER_USAGE_LOG_MAX_BYTES", 5 * 1024 * 1024)),
        backupCount=int(os.environ.get("LAWVER_USAGE_LOG_BACKUPS", 5)),
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    usage_logger.addHandler(file_handler)


_install_usage_log_handler(configured_usage_log_path)

# 进程内限流：仅在单 worker 部署下精确；多 worker 部署需要把状态迁到 Redis 或共享存储。
ip_request_counts = defaultdict(lambda: {"count": 0, "reset_time": 0})
last_rate_limit_prune = 0.0


def get_usage_log_path() -> Path:
    for handler in usage_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            return Path(handler.baseFilename)
    return _configured_usage_log_path()


def clear_usage_logs() -> int:
    cleared_count = 0
    handled_paths: set[Path] = set()

    for handler in usage_logger.handlers:
        if not isinstance(handler, RotatingFileHandler):
            continue

        handler.acquire()
        try:
            handler.flush()
            base_path = Path(handler.baseFilename)
            base_path.parent.mkdir(parents=True, exist_ok=True)
            if handler.stream:
                handler.stream.seek(0)
                handler.stream.truncate()
            else:
                base_path.write_text("", encoding="utf-8")
            handled_paths.add(base_path.resolve())
            cleared_count += 1
        finally:
            handler.release()

        for rotated_path in sorted(base_path.parent.glob(f"{base_path.name}.*")):
            resolved_path = rotated_path.resolve()
            if resolved_path in handled_paths:
                continue
            try:
                rotated_path.unlink()
                handled_paths.add(resolved_path)
                cleared_count += 1
            except FileNotFoundError:
                continue

    if cleared_count == 0:
        base_path = get_usage_log_path()
        if base_path.exists():
            base_path.write_text("", encoding="utf-8")
            cleared_count = 1

    return cleared_count


def should_record_usage_log(method: str, path: str) -> bool:
    return path.startswith("/api") and not (method == "DELETE" and path == "/api/admin/logs")


def origin_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def is_trusted_origin(origin: str | None) -> bool:
    if not origin:
        return False
    normalized = origin.rstrip("/")
    return normalized in ALLOWED_ORIGINS or bool(LOCAL_ORIGIN_RE.match(normalized))


def is_local_host(hostname: str | None) -> bool:
    return hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def is_trusted_proxy_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def client_ip_for_request(request: Request) -> str:
    direct_host = request.client.host if request.client else None
    if is_trusted_proxy_host(direct_host):
        cf_ip = (request.headers.get("cf-connecting-ip") or "").strip()
        if cf_ip:
            return cf_ip
        x_forwarded_for = request.headers.get("x-forwarded-for") or ""
        forwarded_ip = x_forwarded_for.split(",", 1)[0].strip()
        if forwarded_ip:
            return forwarded_ip
    return direct_host or "unknown"


def secure_cookie_for_request(request: Request) -> bool:
    raw = os.getenv("COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return not is_local_host(request.url.hostname)


async def security_and_logging_middleware(request: Request, call_next):
    global last_rate_limit_prune
    client_ip = client_ip_for_request(request)
    method = request.method
    path = request.url.path

    if path.startswith("/api") and method not in SAFE_HTTP_METHODS:
        origin = request.headers.get("origin")
        referer_origin = origin_from_url(request.headers.get("referer"))
        origin_trusted = bool(origin and is_trusted_origin(origin))
        referer_trusted = bool(referer_origin and is_trusted_origin(referer_origin))
        # 任意非 GET API 都必须能从 Origin 或 Referer 中找到一个可信来源,避免无头脚本绕过同源策略。
        if origin and not origin_trusted:
            return Response(content="Forbidden origin", status_code=403)
        if not origin_trusted and referer_origin and not referer_trusted:
            return Response(content="Forbidden referer", status_code=403)
        if not origin_trusted and not referer_trusted:
            return Response(content="Missing origin", status_code=403)

    now = time.time()
    if path.startswith("/api") and method != "OPTIONS":
        if now - last_rate_limit_prune > 60:
            stale_ips = [ip for ip, data in ip_request_counts.items() if now > data["reset_time"]]
            for ip in stale_ips:
                del ip_request_counts[ip]
            last_rate_limit_prune = now

        ip_data = ip_request_counts[client_ip]
        if now > ip_data["reset_time"]:
            ip_data["count"] = 1
            ip_data["reset_time"] = now + 60
        else:
            ip_data["count"] += 1
            if ip_data["count"] > RATE_LIMIT:
                return Response(content="Rate limit exceeded", status_code=429)

    response = await call_next(request)

    if should_record_usage_log(method, path):
        username = "anonymous"
        token = None
        authorization = request.headers.get("authorization")
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not token:
            token = request.cookies.get("auth_token")
        if token:
            user = verify_token(token)
            if user:
                username = user

        client_type = (request.headers.get("x-lawver-client") or "web").strip() or "web"
        usage_logger.info(f"{client_ip} | {username} | {client_type} | {method} | {path} | {response.status_code}")

    return response
