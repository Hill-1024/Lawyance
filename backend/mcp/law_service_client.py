"""自营法库 HTTP 客户端；保持本地检索函数的原始 JSON 契约。

仅按需传输检索结果，不导入 RAG、不写文件、不保存响应缓存。所有请求的地址和
凭据在调用时读取；失败会显式返回上层，绝不回退到客户机器上的本地语料。
"""

from __future__ import annotations

import json
import math
import os
from urllib.parse import urlsplit

import requests


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_TRANSIENT_STATUSES = {500, 502, 503, 504}
_HTTP_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_HTTP_HINTS = {
    400: "查询参数不正确",
    401: "访问密钥无效或缺失",
    403: "访问密钥已禁用或权限不足",
    404: "服务端点不存在，请检查地址与版本",
    429: "请求过于频繁或今日配额已耗尽",
    500: "服务内部错误",
    502: "服务暂时不可用",
    503: "法库索引尚未就绪或服务暂时不可用",
    504: "服务响应超时",
}


class LawServiceError(RuntimeError):
    """可向工具调用者说明的配置、网络或服务错误。"""


def source() -> str | None:
    """显式 local/remote 优先；空值保留原有 PKU_LAW_SOURCE 选择规则。"""
    value = (os.getenv("LAWVER_LAW_SOURCE") or "").strip().lower()
    if not value:
        return None
    if value not in {"local", "remote"}:
        raise LawServiceError("LAWVER_LAW_SOURCE 必须为 local 或 remote")
    return value


def _configuration() -> tuple[str, str, tuple[float, float]]:
    base_url = (os.getenv("LAWVER_LAW_SERVICE_URL") or "").strip().rstrip("/")
    key = (os.getenv("LAWVER_LAW_SERVICE_KEY") or "").strip()
    if not base_url:
        raise LawServiceError("远程法库未配置 LAWVER_LAW_SERVICE_URL")
    try:
        parsed = urlsplit(base_url)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.port != 0
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() or ord(char) < 32 for char in base_url)
        )
    except ValueError:
        valid = False
    if not valid:
        # 不回显 URL，避免 URL 中误填的凭据进入工具结果或日志。
        raise LawServiceError("LAWVER_LAW_SERVICE_URL 必须为不含凭据、查询或片段的 HTTP(S) 地址")
    if parsed.scheme == "http" and parsed.hostname not in _HTTP_LOOPBACK_HOSTS:
        raise LawServiceError("远程法库必须使用 HTTPS，HTTP 仅允许 localhost、127.0.0.1 或 ::1 回环地址")
    if not key:
        raise LawServiceError("远程法库未配置 LAWVER_LAW_SERVICE_KEY")
    if any(char.isspace() or ord(char) < 32 for char in key):
        raise LawServiceError("LAWVER_LAW_SERVICE_KEY 格式无效，请仅填写密钥本身")
    try:
        timeout = float(os.getenv("LAWVER_LAW_SERVICE_TIMEOUT") or "10")
    except (TypeError, ValueError):
        raise LawServiceError("LAWVER_LAW_SERVICE_TIMEOUT 必须为正秒数") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise LawServiceError("LAWVER_LAW_SERVICE_TIMEOUT 必须为正秒数")
    return base_url, key, (min(3.0, timeout), timeout)


def validate_configuration() -> None:
    """启动期只检查配置，不访问网络，服务暂时离线也不影响主应用启动。"""
    _configuration()


def _read_json(response: requests.Response) -> dict:
    body = bytearray()
    for chunk in response.iter_content(chunk_size=65536):
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise LawServiceError("法库服务响应过大")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise LawServiceError("法库服务返回了无效 JSON") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("success"), bool):
        raise LawServiceError("法库服务响应格式不正确")
    return payload


def _validate_result(path: str, payload: dict) -> dict:
    if not payload["success"]:
        if "message" in payload and not isinstance(payload["message"], str):
            raise LawServiceError("法库服务响应格式不正确")
        return payload
    if path.endswith("/links"):
        valid = isinstance(payload.get("text"), str)
    else:
        data = payload.get("data")
        items = data if path.endswith("/search") else [data]
        valid = isinstance(items, list) and all(
            isinstance(item, dict)
            and all(isinstance(item.get(field, ""), str) for field in ("law_name", "article_number", "content", "url"))
            for item in items
        )
    if not valid:
        raise LawServiceError("法库服务响应格式不正确")
    return payload


def _request(path: str, payload: dict) -> str:
    base_url, key, timeout = _configuration()
    for attempt in range(2):
        response = None
        try:
            response = requests.post(
                f"{base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                timeout=timeout,
                # 不跟随重定向，避免将客户密钥发送到其他服务。
                allow_redirects=False,
                stream=True,
            )
            status = response.status_code
            if status in _TRANSIENT_STATUSES and attempt == 0:
                continue
            if not 200 <= status < 300:
                hint = _HTTP_HINTS.get(status, "请求失败，请检查服务配置")
                raise LawServiceError(f"法库服务返回 {status}：{hint}")
            return json.dumps(_validate_result(path, _read_json(response)), ensure_ascii=False)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 0:
                continue
            raise LawServiceError("法条检索暂不可用：连接失败或超时，请稍后重试") from None
        except requests.RequestException:
            # 不串接 requests 的异常文本，其中可能包含 URL、代理凭据等部署信息。
            raise LawServiceError("法条检索暂不可用：网络请求失败") from None
        finally:
            if response is not None:
                response.close()
    raise LawServiceError("法条检索暂不可用")  # pragma: no cover


def law_exact_search(law_name: str, number: str) -> str:
    return _request("/v1/laws/exact", {"title": str(law_name or "").strip()[:160], "number": str(number or "").strip()[:40]})


def law_fuzzy_search(keyword: str, limit: int = 5) -> str:
    return _request("/v1/laws/search", {"query": str(keyword or "").strip()[:4000], "limit": limit})


def law_link_search(message: str, limit: int = 5) -> str:
    return _request("/v1/laws/links", {"text": str(message or "").strip()[:4000], "limit": limit})
