"""
模块描述：WebDAV 数据同步中转 API，为前端提供 test/list/upload/download/delete 端点。
凭据随包传入、服务端用后即弃，不落盘、不入日志。
"""

import base64
import ipaddress
import os
import socket
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException

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
# WebDAV 请求超时（秒）
_REQUEST_TIMEOUT = 30

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地
    ipaddress.ip_network("fc00::/7"),           # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),          # IPv6 链路本地
]


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
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="WebDAV URL 必须使用 http 或 https 协议。")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="WebDAV URL 缺少主机名。")

    allow_private = os.getenv("LAWVER_WEBDAV_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "yes")
    if not allow_private:
        # 解析全部 A/AAAA 记录，防止 DNS rebinding
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="无法解析 WebDAV 主机名。")
        for info in infos:
            ip_str = info[4][0]
            if _is_private_ip(ip_str):
                raise HTTPException(
                    status_code=400,
                    detail=f"WebDAV 主机名 {hostname!r} 解析到私有/保留地址，已拒绝。"
                    " 如需访问局域网 WebDAV，请在服务器设置 LAWVER_WEBDAV_ALLOW_PRIVATE=1。",
                )

    return url.rstrip("/")


def _dir_url(base: str, directory: str) -> str:
    """拼接目录 URL，保证末尾有斜杠。"""
    path = directory.strip()
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path = path + "/"
    return base.rstrip("/") + path


def _file_url(base: str, directory: str, filename: str) -> str:
    import urllib.parse
    return _dir_url(base, directory) + urllib.parse.quote(filename)


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
    except ET.ParseError as exc:
        raise HTTPException(status_code=502, detail=f"无法解析 WebDAV 响应 XML: {exc}")

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
        results.append({
            "filename": filename,
            "size": int(size_el.text) if size_el is not None and size_el.text else 0,
            "last_modified": mtime_el.text if mtime_el is not None else "",
        })

    results.sort(key=lambda x: x["last_modified"], reverse=True)
    return results


# ─── 端点 ───────────────────────────────────────────────────────────────────

@router.post("/api/webdav/test")
async def webdav_test(req: WebDavTestRequest, current_user: str = Depends(get_current_user)):
    """验证连通性并在目录不存在时自动创建。"""
    base = _validate_webdav_url(req.config.url)
    dir_url = _dir_url(base, req.config.directory)
    auth = _auth(req.config)

    try:
        # PROPFIND 检测目录是否存在
        resp = requests.request(
            "PROPFIND",
            dir_url,
            headers={"Depth": "0", "Content-Type": "application/xml"},
            data=_propfind_xml(),
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"无法连接 WebDAV 服务器: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="WebDAV 鉴权失败，请检查用户名和密码。")

    if resp.status_code == 404:
        # 目录不存在，尝试 MKCOL
        try:
            mk = requests.request(
                "MKCOL",
                dir_url,
                auth=auth,
                timeout=_REQUEST_TIMEOUT,
                allow_redirects=False,
            )
        except requests.exceptions.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"创建 WebDAV 目录失败: {exc}")

        if mk.status_code not in (200, 201, 204):
            raise HTTPException(
                status_code=502,
                detail=f"创建 WebDAV 目录失败（状态码 {mk.status_code}）。"
                " 请确认账号有写入权限或手动创建目标目录。",
            )
        return {"status": "ok", "created_directory": True}

    if resp.status_code not in (200, 207):
        raise HTTPException(status_code=502, detail=f"WebDAV 服务器返回异常状态码 {resp.status_code}。")

    return {"status": "ok", "created_directory": False}


@router.post("/api/webdav/list")
async def webdav_list(req: WebDavListRequest, current_user: str = Depends(get_current_user)):
    """列出目录下所有 .json 快照文件。"""
    base = _validate_webdav_url(req.config.url)
    dir_url = _dir_url(base, req.config.directory)
    auth = _auth(req.config)

    try:
        resp = requests.request(
            "PROPFIND",
            dir_url,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            data=_propfind_xml(),
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"无法连接 WebDAV 服务器: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="WebDAV 鉴权失败。")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="WebDAV 目录不存在，请先测试连接以自动创建。")
    if resp.status_code not in (200, 207):
        raise HTTPException(status_code=502, detail=f"WebDAV 服务器返回异常状态码 {resp.status_code}。")

    files = _parse_propfind(resp.text, req.config.directory)
    return {"files": files}


@router.post("/api/webdav/upload")
async def webdav_upload(req: WebDavUploadRequest, current_user: str = Depends(get_current_user)):
    """将 base64 编码的 JSON 备份上传到 WebDAV。"""
    base = _validate_webdav_url(req.config.url)
    auth = _auth(req.config)

    # 文件名校验：只允许合理字符，防止路径注入
    filename = req.filename.strip()
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名。")
    if not filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="备份文件名必须以 .json 结尾。")

    try:
        raw = base64.b64decode(req.data_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="data_b64 不是合法的 base64 数据。")

    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"备份文件超过上限 {_MAX_UPLOAD_BYTES // 1024 // 1024} MB。")

    file_url = _file_url(base, req.config.directory, filename)
    try:
        resp = requests.put(
            file_url,
            data=raw,
            headers={"Content-Type": "application/json"},
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"上传失败: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="WebDAV 鉴权失败。")
    if resp.status_code not in (200, 201, 204):
        raise HTTPException(status_code=502, detail=f"WebDAV 上传失败（状态码 {resp.status_code}）。")

    return {"status": "ok", "filename": filename}


@router.post("/api/webdav/download")
async def webdav_download(req: WebDavDownloadRequest, current_user: str = Depends(get_current_user)):
    """从 WebDAV 拉取指定文件，返回 base64 编码内容。"""
    base = _validate_webdav_url(req.config.url)
    auth = _auth(req.config)

    filename = req.filename.strip()
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名。")

    file_url = _file_url(base, req.config.directory, filename)
    try:
        resp = requests.get(
            file_url,
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"下载失败: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="WebDAV 鉴权失败。")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="文件不存在。")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"WebDAV 下载失败（状态码 {resp.status_code}）。")

    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="远端文件超过允许下载的上限。")
        chunks.append(chunk)

    raw = b"".join(chunks)
    return {"data_b64": base64.b64encode(raw).decode()}


@router.post("/api/webdav/delete")
async def webdav_delete(req: WebDavDeleteRequest, current_user: str = Depends(get_current_user)):
    """删除 WebDAV 上的指定快照文件。"""
    base = _validate_webdav_url(req.config.url)
    auth = _auth(req.config)

    filename = req.filename.strip()
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名。")

    file_url = _file_url(base, req.config.directory, filename)
    try:
        resp = requests.request(
            "DELETE",
            file_url,
            auth=auth,
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"删除失败: {exc}")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="WebDAV 鉴权失败。")
    if resp.status_code not in (200, 204, 404):
        raise HTTPException(status_code=502, detail=f"WebDAV 删除失败（状态码 {resp.status_code}）。")

    return {"status": "ok"}
