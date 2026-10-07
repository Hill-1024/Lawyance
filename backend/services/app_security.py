"""
模块描述：应用级限流、JSON 体限长、访问日志与请求防护中间件。
"""

from logging.handlers import RotatingFileHandler
from pathlib import Path
import ipaddress
import json
import logging
import os

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from auth import verify_token_for_request
from services import rate_limit


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
# 通用桶按出口 IP 计数：流式回复期间事件轮询 ≥1s/次（≈60-100 次/分钟），再叠加
# 发送/上传后的索引刷新与多标签页、同一律所/回环代理后的多会话，100 次/60s 会让
# 正常用户互相打满（大量 429、假登出、误报网络失败），600 只给正常交互留余量，
# 依然拦得住脚本洪水。
RATE_LIMIT = _bounded_env_int("LAWVER_API_RATE_LIMIT", 600, 1, 1_000_000)
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


def _configured_multipart_body_limit() -> int:
    """multipart 的中间件级上限。工作区上传/头像在端点里有更小的逐端点限长，
    这里只需罩住最大的合法 multipart——工作台备份恢复允许 256 MB（BACKUP_MAX_BYTES），
    留出编码开销余量。"""
    try:
        configured = int(os.getenv("LAWVER_MAX_UPLOAD_BODY_BYTES", str(264 * 1024 * 1024)))
    except ValueError:
        configured = 264 * 1024 * 1024
    return min(max(configured, 1024 * 1024), 1024 * 1024 * 1024)


MAX_UPLOAD_BODY_BYTES = _configured_multipart_body_limit()


def _json_body_limit_for_path(path: str) -> int:
    if path == "/api/login":
        route_limit = LOGIN_JSON_BODY_BYTES
    elif path in {
        "/api/admin/accounts",
        "/api/settings/secret",
        "/api/settings/secret/clear",
        "/api/court/memory/clear",
    }:
        route_limit = SMALL_CONTROL_JSON_BODY_BYTES
    elif path == "/api/court/turn":
        route_limit = CHAT_JSON_BODY_BYTES
    else:
        route_limit = MAX_JSON_BODY_BYTES
    return min(MAX_JSON_BODY_BYTES, route_limit)


def _configured_usage_log_path() -> Path:
    explicit_path = os.getenv("LAWVER_USAGE_LOG_PATH")
    if explicit_path:
        return Path(explicit_path)
    return Path(os.getenv("LAWVER_DATA_DIR", "data")) / "usage.log"


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
    # 分流核心每 5s 探活一次 /api/health：那是机器流量，记进访问日志只会把真实用户行为淹掉。
    if path == "/api/health":
        return False
    return path.startswith("/api") and not (method == "DELETE" and path == "/api/admin/logs")


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


def _forwarded_scheme(request: Request) -> str:
    """回环可信代理转来的访客协议：X-Forwarded-Proto 优先，Cloudflare 用 cf-visitor。"""
    proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    if proto:
        return proto
    raw = (request.headers.get("cf-visitor") or "").strip()
    if raw:
        # cf-visitor 是外部可控的头：合法 JSON 但不是对象（null/[]/123/"https"）时
        # 不能让 AttributeError 一路炸到登录接口 500。
        try:
            parsed = json.loads(raw)
        except ValueError:
            return ""
        if not isinstance(parsed, dict):
            return ""
        return str(parsed.get("scheme") or "").strip().lower()
    return ""


def secure_cookie_for_request(request: Request) -> bool:
    raw = os.getenv("COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    # 文档化生产拓扑（deploy/router 在回环、上游 127.0.0.1:8081 且 Host 按逐跳头丢弃）
    # 里应用看到的 Host 恒为回环：按 Host 判断会把 auth_token 以无 Secure 属性下发。
    # 回环来源先读代理转发的访客协议；拿不到就默认加 Secure——现代浏览器对
    # localhost/127.0.0.1 也接受 Secure Cookie，本地开发不受影响，确需明文调试时
    # 用 COOKIE_SECURE=0 显式关闭。非回环直连维持原判。
    direct_host = request.client.host if request.client else None
    if is_trusted_proxy_host(direct_host):
        proto = _forwarded_scheme(request)
        if proto:
            return proto == "https"
        return True
    return not is_local_host(request.url.hostname)


def _has_json_content_type(request: Request) -> bool:
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def _has_multipart_content_type(request: Request) -> bool:
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return media_type == "multipart/form-data"


def _body_too_large_response() -> Response:
    return JSONResponse(
        status_code=413,
        content={"detail": "Request body too large", "code": "request_body_too_large"},
    )


async def _guard_multipart_body(request: Request) -> Response | None:
    """multipart 不走 JSON 分支：Starlette 会先把整个 body 流式 spool 落盘
    （UploadFile 超 1MB 即写临时文件），端点里 read(N+1) 的限长生效时磁盘已经
    被写过了——攻击者反复推 GB 级 body 即可耗尽磁盘。这里提前拦截：

    - 带 Content-Length：超限直接 413，一个字节都不读；
    - chunked（无 Content-Length）：增量消费计数，超限即 413（消费即丢弃，
      不落盘）；限内把已读字节回放进 request._body，由 BaseHTTPMiddleware 的
      wrapped_receive 原样交给下游 multipart 解析器（与 JSON 分支同一回放机制）。
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > MAX_UPLOAD_BODY_BYTES:
            return _body_too_large_response()
        # 声明了长度且在限内：交给 Starlette 正常流式接收，端点侧另有逐端点上限。
        return None

    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_UPLOAD_BODY_BYTES:
                return _body_too_large_response()
            if chunk:
                chunks.append(chunk)
    except ClientDisconnect:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid request body", "code": "invalid_request_body"},
        )
    request._body = b"".join(chunks)
    return None


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
    # 429 也走全站 {"detail": ...} JSON 错误契约：纯文本体会被前端兜底成
    # 「网络请求失败」，把服务端限流误报成用户网络故障。Retry-After 保留，
    # 前端据此提示「N 秒后再试」。
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded", "code": "rate_limited"},
        headers={"Retry-After": str(max(int(retry_after), 1))},
    )


async def security_and_logging_middleware(request: Request, call_next):
    client_ip = client_ip_for_request(request)
    method = request.method
    path = request.url.path

    # 限流放在读取请求体之前：无效洪水应当只花一次计数，而不是先把 40MB 读进来。
    # 登录只走专用登录桶、不进通用桶：登录是每个用户每会话一次的低频请求，把它
    # 前置进通用桶会让「别的 API 流量打满预算」（视口扫描、流式轮询、共享出口 IP
    # 的多会话）连带把登录 429 掉——页面停在 /login 打不进 /home。撞库防护不受
    # 影响：同 IP 喷用户名由 LOGIN_RATE_LIMIT（30 次/分/IP）单独兜住。
    if path.startswith("/api") and method != "OPTIONS":
        if path == "/api/login":
            login = rate_limit.hit(
                "login", client_ip, limit=LOGIN_RATE_LIMIT, window_seconds=RATE_LIMIT_WINDOW_SECONDS
            )
            if not login.allowed:
                return _rate_limited_response(login.retry_after)
        else:
            general = rate_limit.hit(
                "api", client_ip, limit=RATE_LIMIT, window_seconds=RATE_LIMIT_WINDOW_SECONDS
            )
            if not general.allowed:
                return _rate_limited_response(general.retry_after)

    if _has_json_content_type(request):
        body_error = await _buffer_json_body_with_limit(request, _json_body_limit_for_path(path))
        if body_error is not None:
            return body_error
    elif _has_multipart_content_type(request):
        body_error = await _guard_multipart_body(request)
        if body_error is not None:
            return body_error

    response = await call_next(request)

    # 全站禁止 MIME 嗅探：用户可控字节（如头像）只能按声明的图片类型渲染，
    # 不给浏览器把响应猜成 HTML/JS 再执行的空间。
    response.headers["X-Content-Type-Options"] = "nosniff"

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
            # 路由依赖若已验证过同一 token，这里直接复用请求级缓存的结果。
            user = await run_in_threadpool(
                verify_token_for_request, request.scope, token
            )
            if user:
                username = user

        client_type = (request.headers.get("x-lawver-client") or "web").strip() or "web"
        usage_logger.info(f"{client_ip} | {username} | {client_type} | {method} | {path} | {response.status_code}")

    return response
