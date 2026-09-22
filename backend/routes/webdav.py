"""
模块描述：WebDAV 数据同步中转 API，为前端提供 test/list/upload/download/delete 端点。
凭据随包传入、服务端用后即弃，不落盘、不入日志。
"""

import asyncio
import base64
import binascii
import ipaddress
import os
import socket
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException
from requests.adapters import HTTPAdapter
from requests.exceptions import ProxyError
from requests.utils import select_proxy
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from schemas import (
    WebDavConfig,
    WebDavDeleteRequest,
    WebDavDownloadRequest,
    WebDavListRequest,
    WebDavTestRequest,
    WebDavUploadRequest,
)
from services.auth_dependencies import get_current_user

router = APIRouter()

# 单次传输上限 25 MB（base64 解码后）
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# base64 最多膨胀约 4/3；先限制编码长度，避免解码前就分配超大对象。
_MAX_UPLOAD_B64_CHARS = 4 * ((_MAX_UPLOAD_BYTES + 2) // 3)
# PROPFIND 响应只需要文件元数据，超过该预算直接拒绝。
_MAX_PROPFIND_BYTES = 2 * 1024 * 1024
_MAX_LISTED_FILES = 1000
# WebDAV 请求超时（秒）
_REQUEST_TIMEOUT = 30
_BACKUP_SUFFIX = ".json"
_MAX_RESOLVED_ADDRESSES = 8

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地
    ipaddress.ip_network("fc00::/7"),           # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),          # IPv6 链路本地
]


def _allow_private_webdav() -> bool:
    return os.getenv("LAWVER_WEBDAV_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "yes")


def _resolve_webdav_addresses(hostname: str, port: int | None, *, allow_private: bool) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="无法解析 WebDAV 主机名。") from None

    addresses: list[str] = []
    for info in infos:
        ip_str = info[4][0]
        if not allow_private and _is_private_ip(ip_str):
            raise HTTPException(
                status_code=400,
                detail=f"WebDAV 主机名 {hostname!r} 解析到私有/保留地址，已拒绝。"
                " 如需访问局域网 WebDAV，请在服务器设置 LAWVER_WEBDAV_ALLOW_PRIVATE=1。",
            )
        if ip_str not in addresses and len(addresses) < _MAX_RESOLVED_ADDRESSES:
            addresses.append(ip_str)
    if not addresses:
        raise HTTPException(status_code=400, detail="无法解析 WebDAV 主机名。")
    return tuple(addresses)


class _PinnedConnectionMixin:
    """Keep the original hostname for Host/SNI while connecting to a vetted IP."""

    def __init__(self, *args, pinned_ip: str, **kwargs):
        self._lawver_pinned_ip = pinned_ip
        super().__init__(*args, **kwargs)

    def _new_conn(self):
        original_dns_host = self._dns_host
        self._dns_host = self._lawver_pinned_ip
        try:
            return super()._new_conn()
        finally:
            self._dns_host = original_dns_host


class _PinnedHTTPConnection(_PinnedConnectionMixin, HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, HTTPSConnection):
    pass


class _PinnedHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection

    def __init__(self, host, port=None, *, pinned_ip: str, **kwargs):
        super().__init__(host, port, pinned_ip=pinned_ip, **kwargs)


class _PinnedHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection

    def __init__(self, host, port=None, *, pinned_ip: str, **kwargs):
        super().__init__(host, port, pinned_ip=pinned_ip, **kwargs)


class _PinnedDNSAdapter(HTTPAdapter):
    def __init__(self, pinned_ip: str):
        self._pinned_ip = pinned_ip
        super().__init__(max_retries=0)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        if select_proxy(request.url, proxies or {}):
            raise ProxyError("WebDAV requests do not permit forwarding proxies")
        host_params, pool_kwargs = self.build_connection_pool_key_attributes(request, verify, cert)
        scheme = host_params.pop("scheme")
        pool_class = _PinnedHTTPSConnectionPool if scheme == "https" else _PinnedHTTPConnectionPool
        if scheme == "http":
            # Requests 2.34 includes TLS verification keys even for clear-text
            # pools; urllib3's HTTPConnection correctly rejects those keys.
            for key in (
                "cert_reqs",
                "ca_certs",
                "ca_cert_dir",
                "ca_cert_data",
                "ssl_context",
                "cert_file",
                "key_file",
                "key_password",
                "ssl_minimum_version",
                "ssl_maximum_version",
                "ssl_version",
                "assert_hostname",
                "assert_fingerprint",
                "server_hostname",
            ):
                pool_kwargs.pop(key, None)
        return pool_class(
            host=host_params["host"],
            port=host_params["port"],
            pinned_ip=self._pinned_ip,
            **pool_kwargs,
        )


def _is_private_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if addr.is_loopback or addr.is_reserved or addr.is_unspecified or addr.is_multicast:
        return True
    return any(addr in net for net in _PRIVATE_NETWORKS)


def _validate_webdav_url(url: str) -> str:
    """
    校验 WebDAV URL，拒绝非法 scheme 和 SSRF 目标（私有/环回/保留 IP）。
    LAWVER_WEBDAV_ALLOW_PRIVATE=1 可放行自托管局域网。
    返回规范化 URL（去除末尾斜杠）。
    """
    if any(ord(char) < 32 for char in url) or "\\" in url:
        raise HTTPException(status_code=400, detail="WebDAV URL 格式非法。")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="WebDAV URL 必须使用 http 或 https 协议。")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="WebDAV URL 缺少主机名。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="WebDAV URL 不允许包含用户信息、查询参数或片段。")
    if "%" in parsed.netloc:
        raise HTTPException(status_code=400, detail="WebDAV URL 主机名格式非法。")
    try:
        parsed.port
    except ValueError:
        raise HTTPException(status_code=400, detail="WebDAV URL 端口格式非法。") from None

    _resolve_webdav_addresses(hostname, parsed.port, allow_private=_allow_private_webdav())

    return url.rstrip("/")


def _validated_directory(directory: str) -> str:
    path = directory.strip()
    if any(ord(char) < 32 for char in path) or any(char in path for char in ("\\", "?", "#")):
        raise HTTPException(status_code=400, detail="WebDAV 目录格式非法。")
    decoded_parts = unquote(path).split("/")
    if any(part in {".", ".."} for part in decoded_parts):
        raise HTTPException(status_code=400, detail="WebDAV 目录不能包含相对路径段。")
    return path


def _dir_url(base: str, directory: str) -> str:
    """拼接目录 URL，保证末尾有斜杠。"""
    path = _validated_directory(directory)
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path = path + "/"
    return base.rstrip("/") + path


def _file_url(base: str, directory: str, filename: str) -> str:
    import urllib.parse
    return _dir_url(base, directory) + urllib.parse.quote(filename, safe="")


def _validate_backup_filename(filename: str) -> str:
    normalized = filename.strip()
    if (
        not normalized
        or len(normalized) > 255
        or "/" in normalized
        or "\\" in normalized
        or ".." in normalized
        or any(ord(char) < 32 for char in normalized)
    ):
        raise HTTPException(status_code=400, detail="非法文件名。")
    if not normalized.lower().endswith(_BACKUP_SUFFIX):
        raise HTTPException(status_code=400, detail="备份文件名必须以 .json 结尾。")
    return normalized


def _auth(cfg: WebDavConfig):
    return (cfg.username, cfg.password)


def _propfind_xml() -> str:
    return '<?xml version="1.0" encoding="utf-8"?><D:propfind xmlns:D="DAV:"><D:prop><D:displayname/><D:getcontentlength/><D:getlastmodified/><D:resourcetype/></D:prop></D:propfind>'


def _parse_propfind(xml_text: str, directory: str) -> list[dict]:
    """
    解析 PROPFIND depth=1 响应，返回目录内 .json 文件列表。
    """
    import urllib.parse
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise HTTPException(status_code=502, detail="无法解析 WebDAV 文件列表响应。") from None

    ns = {"D": "DAV:"}
    results = []
    dir_path = directory.strip().rstrip("/")

    for response in root.findall(".//D:response", ns):
        href_el = response.find("D:href", ns)
        if href_el is None:
            continue
        href = (href_el.text or "").rstrip("/")

        # 跳过目录本身
        # 如果 dir_path 为空，代表根目录，此时只有 href 为空或 "/" 时才跳过目录本身
        if dir_path == "":
            if href.rstrip("/") == "":
                continue
        elif href.rstrip("/").endswith(dir_path):
            continue

        # 跳过集合（子目录）
        resourcetype = response.find(".//D:resourcetype", ns)
        if resourcetype is not None and resourcetype.find("D:collection", ns) is not None:
            continue

        filename_raw = href.split("/")[-1]
        filename = urllib.parse.unquote(filename_raw)
        if not filename.endswith(".json"):
            continue

        size_el = response.find(".//D:getcontentlength", ns)
        mtime_el = response.find(".//D:getlastmodified", ns)
        try:
            size = max(0, int(size_el.text)) if size_el is not None and size_el.text else 0
        except (TypeError, ValueError):
            size = 0
        results.append({
            "filename": filename,
            "size": size,
            "last_modified": mtime_el.text if mtime_el is not None else "",
        })
        if len(results) >= _MAX_LISTED_FILES:
            break

    results.sort(key=lambda x: x["last_modified"], reverse=True)
    return results


class _RemoteResponseTooLarge(Exception):
    pass


def _request_remote(method: str, url: str, **kwargs) -> requests.Response:
    """Resolve, validate, then pin the connection to exactly that vetted IP."""
    parsed = urlparse(url)
    if not parsed.hostname or parsed.scheme not in ("http", "https"):
        raise requests.exceptions.InvalidURL("invalid WebDAV target")
    addresses = _resolve_webdav_addresses(
        parsed.hostname,
        parsed.port,
        allow_private=_allow_private_webdav(),
    )
    if kwargs.get("allow_redirects") is not False:
        raise requests.exceptions.InvalidURL("WebDAV redirects must stay disabled")

    request_kwargs = dict(kwargs)
    timeout_value = request_kwargs.get("timeout", _REQUEST_TIMEOUT)
    try:
        total_timeout = min(max(float(timeout_value), 0.1), float(_REQUEST_TIMEOUT))
    except (TypeError, ValueError, OverflowError):
        raise requests.exceptions.InvalidURL("invalid WebDAV timeout") from None
    deadline = time.monotonic() + total_timeout
    last_error: requests.exceptions.RequestException | None = None

    for pinned_ip in addresses:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        request_kwargs["timeout"] = remaining
        session = requests.Session()
        session.trust_env = False
        session.mount(f"{parsed.scheme}://", _PinnedDNSAdapter(pinned_ip))
        try:
            response = session.request(method, url, proxies={}, **request_kwargs)
        except requests.exceptions.RequestException as exc:
            last_error = exc
            session.close()
            continue
        except BaseException:
            session.close()
            raise

        original_close = response.close
        closed = False

        def close_response_and_session() -> None:
            nonlocal closed
            if closed:
                return
            closed = True
            try:
                original_close()
            finally:
                session.close()

        response.close = close_response_and_session
        return response

    if last_error is not None:
        raise last_error
    raise requests.exceptions.ConnectTimeout("WebDAV connection timed out")


def _read_bounded_response(response: requests.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise _RemoteResponseTooLarge
        chunks.append(chunk)
    return b"".join(chunks)


def _request_bounded_body(method: str, url: str, *, max_bytes: int, **kwargs) -> tuple[int, bytes]:
    response = _request_remote(method, url, stream=True, **kwargs)
    try:
        body = _read_bounded_response(response, max_bytes)
        return response.status_code, body
    finally:
        response.close()


def _request_status(method: str, url: str, **kwargs) -> int:
    """Issue a status-only request without buffering an untrusted response body."""
    response = _request_remote(method, url, stream=True, **kwargs)
    try:
        return response.status_code
    finally:
        response.close()


def _put_status(url: str, **kwargs) -> int:
    response = _request_remote("PUT", url, stream=True, **kwargs)
    try:
        return response.status_code
    finally:
        response.close()


def _download_bounded(url: str, *, max_bytes: int, **kwargs) -> tuple[int, bytes]:
    response = _request_remote("GET", url, stream=True, **kwargs)
    try:
        if response.status_code != 200:
            return response.status_code, b""
        return response.status_code, _read_bounded_response(response, max_bytes)
    finally:
        response.close()


def _remote_auth_error() -> HTTPException:
    # 远端 WebDAV 的 401 不能冒充本应用会话过期，否则前端会清除 Lawver 登录态。
    return HTTPException(status_code=400, detail="WebDAV 鉴权失败，请检查用户名和密码。")


# ─── 端点 ───────────────────────────────────────────────────────────────────

@router.post("/api/webdav/test")
async def webdav_test(req: WebDavTestRequest, current_user: str = Depends(get_current_user)):
    """验证连通性并在目录不存在时自动创建。"""
    base = await asyncio.to_thread(_validate_webdav_url, req.config.url)
    dir_url = _dir_url(base, req.config.directory)
    auth = _auth(req.config)

    try:
        # PROPFIND 检测目录是否存在
        status_code = await asyncio.to_thread(
            _request_status,
            "PROPFIND",
            dir_url,
            headers={"Depth": "0", "Content-Type": "application/xml"},
            data=_propfind_xml(),
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException:
        raise HTTPException(status_code=502, detail="无法连接 WebDAV 服务器。")

    if status_code == 401:
        raise _remote_auth_error()

    if status_code == 404:
        # 目录不存在，尝试 MKCOL
        try:
            mk_status = await asyncio.to_thread(
                _request_status,
                "MKCOL",
                dir_url,
                auth=auth,
                timeout=_REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException:
            raise HTTPException(status_code=502, detail="创建 WebDAV 目录失败。")

        if mk_status not in (200, 201, 204):
            raise HTTPException(
                status_code=502,
                detail=f"创建 WebDAV 目录失败（状态码 {mk_status}）。"
                " 请确认账号有写入权限或手动创建目标目录。",
            )
        return {"status": "ok", "created_directory": True}

    if status_code not in (200, 207):
        raise HTTPException(status_code=502, detail=f"WebDAV 服务器返回异常状态码 {status_code}。")

    return {"status": "ok", "created_directory": False}


@router.post("/api/webdav/list")
async def webdav_list(req: WebDavListRequest, current_user: str = Depends(get_current_user)):
    """列出目录下所有 .json 快照文件。"""
    base = await asyncio.to_thread(_validate_webdav_url, req.config.url)
    dir_url = _dir_url(base, req.config.directory)
    auth = _auth(req.config)

    try:
        status_code, response_body = await asyncio.to_thread(
            _request_bounded_body,
            "PROPFIND",
            dir_url,
            max_bytes=_MAX_PROPFIND_BYTES,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            data=_propfind_xml(),
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except _RemoteResponseTooLarge:
        raise HTTPException(status_code=413, detail="WebDAV 文件列表响应过大。")
    except requests.exceptions.RequestException:
        raise HTTPException(status_code=502, detail="无法连接 WebDAV 服务器。")

    if status_code == 401:
        raise _remote_auth_error()
    if status_code == 404:
        raise HTTPException(status_code=404, detail="WebDAV 目录不存在，请先测试连接以自动创建。")
    if status_code not in (200, 207):
        raise HTTPException(status_code=502, detail=f"WebDAV 服务器返回异常状态码 {status_code}。")

    files = await asyncio.to_thread(
        _parse_propfind,
        response_body.decode("utf-8", errors="replace"),
        req.config.directory,
    )
    return {"files": files}


@router.post("/api/webdav/upload")
async def webdav_upload(req: WebDavUploadRequest, current_user: str = Depends(get_current_user)):
    """将 base64 编码的 JSON 备份上传到 WebDAV。"""
    base = await asyncio.to_thread(_validate_webdav_url, req.config.url)
    auth = _auth(req.config)

    # 文件名校验：只允许合理字符，防止路径注入
    filename = _validate_backup_filename(req.filename)

    if len(req.data_b64) > _MAX_UPLOAD_B64_CHARS:
        raise HTTPException(status_code=413, detail=f"备份文件超过上限 {_MAX_UPLOAD_BYTES // 1024 // 1024} MB。")
    try:
        raw = await asyncio.to_thread(base64.b64decode, req.data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="data_b64 不是合法的 base64 数据。")

    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"备份文件超过上限 {_MAX_UPLOAD_BYTES // 1024 // 1024} MB。")

    file_url = _file_url(base, req.config.directory, filename)
    try:
        status_code = await asyncio.to_thread(
            _put_status,
            file_url,
            data=raw,
            headers={"Content-Type": "application/json"},
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException:
        raise HTTPException(status_code=502, detail="WebDAV 上传失败。")

    if status_code == 401:
        raise _remote_auth_error()
    if status_code not in (200, 201, 204):
        raise HTTPException(status_code=502, detail=f"WebDAV 上传失败（状态码 {status_code}）。")

    return {"status": "ok", "filename": filename}


@router.post("/api/webdav/download")
async def webdav_download(req: WebDavDownloadRequest, current_user: str = Depends(get_current_user)):
    """从 WebDAV 拉取指定文件，返回 base64 编码内容。"""
    base = await asyncio.to_thread(_validate_webdav_url, req.config.url)
    auth = _auth(req.config)

    filename = _validate_backup_filename(req.filename)

    file_url = _file_url(base, req.config.directory, filename)
    try:
        status_code, raw = await asyncio.to_thread(
            _download_bounded,
            file_url,
            max_bytes=_MAX_UPLOAD_BYTES,
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except _RemoteResponseTooLarge:
        raise HTTPException(status_code=413, detail="远端文件超过允许下载的上限。")
    except requests.exceptions.RequestException:
        raise HTTPException(status_code=502, detail="WebDAV 下载失败。")

    if status_code == 401:
        raise _remote_auth_error()
    if status_code == 404:
        raise HTTPException(status_code=404, detail="文件不存在。")
    if status_code != 200:
        raise HTTPException(status_code=502, detail=f"WebDAV 下载失败（状态码 {status_code}）。")

    encoded = await asyncio.to_thread(lambda: base64.b64encode(raw).decode("ascii"))
    return {"data_b64": encoded}


@router.post("/api/webdav/delete")
async def webdav_delete(req: WebDavDeleteRequest, current_user: str = Depends(get_current_user)):
    """删除 WebDAV 上的指定快照文件。"""
    base = await asyncio.to_thread(_validate_webdav_url, req.config.url)
    auth = _auth(req.config)

    filename = _validate_backup_filename(req.filename)

    file_url = _file_url(base, req.config.directory, filename)
    try:
        status_code = await asyncio.to_thread(
            _request_status,
            "DELETE",
            file_url,
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException:
        raise HTTPException(status_code=502, detail="WebDAV 删除失败。")

    if status_code == 401:
        raise _remote_auth_error()
    if status_code not in (200, 204, 404):
        raise HTTPException(status_code=502, detail=f"WebDAV 删除失败（状态码 {status_code}）。")

    return {"status": "ok"}
