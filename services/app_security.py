"""
模块描述：应用级 CORS、CSRF、限流和访问日志中间件。
"""

from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse
import ipaddress
import logging
import os
import re

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from auth import verify_token
from services import rate_limit


SECURE_ORIGIN = "https://law.mutsumi.moe"
NATIVE_CLIENT_ORIGINS = {"https://localhost", "capacitor://localhost"}
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_ORIGIN_RE = re.compile(r"^https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d+)?$")
DEFAULT_TRUSTED_PROXY_CIDRS = ("127.0.0.0/8", "::1/128")
RATE_LIMIT_WINDOW_SECONDS = 60


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.getenv(name, str(default)) or default)
    except ValueError:
        configured = default
    return min(max(configured, minimum), maximum)


# 通用 API 桶与登录桶分开：撞库是「同一 IP 喷洒大量用户名」，账号级锁定拦不住，
# 只能靠 IP 维度的登录限流。计数默认走 Redis 共享，未配置时退回进程内。
RATE_LIMIT = _bounded_env_int("LAWVER_API_RATE_LIMIT", 100, 1, 1_000_000)
LOGIN_RATE_LIMIT = _bounded_env_int("LAWVER_LOGIN_RATE_LIMIT", 30, 1, 100_000)


def _configured_json_body_limit() -> int:
    try:
        configured = int(os.getenv("LAWVER_MAX_JSON_BODY_BYTES", str(40 * 1024 * 1024)))
    except ValueError:
        configured = 40 * 1024 * 1024
    return min(max(configured, 64 * 1024), 256 * 1024 * 1024)


MAX_JSON_BODY_BYTES = _configured_json_body_limit()
LOGIN_JSON_BODY_BYTES = 16 * 1024
SMALL_CONTROL_JSON_BODY_BYTES = 64 * 1024
CHAT_JSON_BODY_BYTES = 12 * 1024 * 1024


def _json_body_limit_for_path(path: str) -> int:
    if path == "/api/login":
        route_limit = LOGIN_JSON_BODY_BYTES
    elif path in {
        "/api/admin/accounts",
        "/api/settings/secret",
        "/api/settings/secret/clear",
        "/api/chat/ack",
        "/api/chat/cancel",
        "/api/court/memory/clear",
    }:
        route_limit = SMALL_CONTROL_JSON_BODY_BYTES
    elif path in {"/api/chat", "/api/memory/sync", "/api/court/turn"}:
        route_limit = CHAT_JSON_BODY_BYTES
    elif path == "/api/summarize":
        route_limit = 4 * 1024 * 1024
    else:
        route_limit = MAX_JSON_BODY_BYTES
    return min(MAX_JSON_BODY_BYTES, route_limit)


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
    # 访问日志含客户端 IP 与用户名，必须与账号文件同级收紧权限。
    for candidate in (log_path, *Path(log_path).parent.glob(f"{Path(log_path).name}.*")):
        try:
            os.chmod(candidate, 0o600)
        except OSError:
            continue


_install_usage_log_handler(configured_usage_log_path)


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


def _configured_trusted_proxy_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    networks = [ipaddress.ip_network(cidr) for cidr in DEFAULT_TRUSTED_PROXY_CIDRS]
    raw_value = os.getenv("LAWVER_TRUSTED_PROXY_CIDRS", "")
    for item in raw_value.split(","):
        cidr = item.strip()
        if not cidr:
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            usage_logger.warning("Ignoring invalid LAWVER_TRUSTED_PROXY_CIDRS entry: %s", cidr)
    return tuple(networks)


def is_trusted_proxy_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return any(ip in network for network in _configured_trusted_proxy_networks())


def _validated_forwarded_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().strip("[]")
    if not candidate:
        return None
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def client_ip_for_request(request: Request) -> str:
    direct_host = request.client.host if request.client else None
    if is_trusted_proxy_host(direct_host):
        cf_ip = _validated_forwarded_ip(request.headers.get("cf-connecting-ip"))
        if cf_ip:
            return cf_ip
        x_forwarded_for = request.headers.get("x-forwarded-for") or ""
        forwarded_ip = _validated_forwarded_ip(x_forwarded_for.split(",", 1)[0])
        if forwarded_ip:
            return forwarded_ip
    return direct_host or "unknown"


def secure_cookie_for_request(request: Request) -> bool:
    raw = os.getenv("COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return not is_local_host(request.url.hostname)


def _has_json_content_type(request: Request) -> bool:
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


async def _buffer_json_body_with_limit(request: Request, limit: int | None = None) -> Response | None:
    """Read JSON incrementally so chunked requests cannot bypass the global cap."""
    limit = MAX_JSON_BODY_BYTES if limit is None else max(int(limit), 0)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = -1
        if declared_length > limit:
            return JSONResponse(
                status_code=413,
                content={"detail": "JSON request body too large", "code": "json_body_too_large"},
            )

    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "JSON request body too large", "code": "json_body_too_large"},
                )
            if chunk:
                chunks.append(chunk)
    except ClientDisconnect:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid request body", "code": "invalid_request_body"},
        )

    # BaseHTTPMiddleware's cached request will replay this bounded body to the
    # downstream FastAPI parser after the original receive channel is consumed.
    request._body = b"".join(chunks)
    return None


def _rate_limited_response(retry_after: int) -> Response:
    return Response(
        content="Rate limit exceeded",
        status_code=429,
        headers={"Retry-After": str(max(int(retry_after), 1))},
    )


async def security_and_logging_middleware(request: Request, call_next):
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

    # 限流放在读取请求体之前：无效洪水应当只花一次计数，而不是先把 40MB 读进来。
    if path.startswith("/api") and method != "OPTIONS":
        general = rate_limit.hit(
            "api", client_ip, limit=RATE_LIMIT, window_seconds=RATE_LIMIT_WINDOW_SECONDS
        )
        if not general.allowed:
            return _rate_limited_response(general.retry_after)
        if path == "/api/login":
            login = rate_limit.hit(
                "login", client_ip, limit=LOGIN_RATE_LIMIT, window_seconds=RATE_LIMIT_WINDOW_SECONDS
            )
            if not login.allowed:
                return _rate_limited_response(login.retry_after)

    if _has_json_content_type(request):
        body_error = await _buffer_json_body_with_limit(request, _json_body_limit_for_path(path))
        if body_error is not None:
            return body_error

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
            # verify_token 会 chmod/读盘并可能抢账号文件锁；放在事件循环里会阻塞所有 SSE。
            user = await run_in_threadpool(verify_token, token)
            if user:
                username = user

        client_type = (request.headers.get("x-lawver-client") or "web").strip() or "web"
        usage_logger.info(f"{client_ip} | {username} | {client_type} | {method} | {path} | {response.status_code}")

    return response
