"""
模块描述：可选的 Redis 后端接入层，为限流与布隆过滤器提供跨 worker 共享状态。

设计约束：
- Redis 是「防护层」而不是数据源，任何连接/命令失败都必须降级而不是抛错，
  否则 Redis 抖动会把整个鉴权链路一起拖垮。
- 连接失败后在冷却窗口内直接判定为不可用，避免每个请求都去踩一次连接超时。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

_logger = logging.getLogger("lawver.redis")

DEFAULT_PREFIX = "lawver"
DEFAULT_TIMEOUT_SECONDS = 0.25
DEFAULT_DOWN_COOLDOWN_SECONDS = 30.0

_CLIENT_LOCK = threading.Lock()
_CLIENT: Optional[Any] = None
_CLIENT_URL: Optional[str] = None
_DOWN_UNTIL = 0.0


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def redis_url() -> str:
    """优先读取 LAWVER_REDIS_URL，其次兼容通用的 REDIS_URL。"""
    for name in ("LAWVER_REDIS_URL", "REDIS_URL"):
        raw = os.getenv(name)
        if raw and raw.strip():
            return raw.strip()
    return ""


def is_configured() -> bool:
    return bool(redis_url())


def prefix() -> str:
    return (os.getenv("LAWVER_REDIS_PREFIX") or DEFAULT_PREFIX).strip() or DEFAULT_PREFIX


def timeout_seconds() -> float:
    return _env_float("LAWVER_REDIS_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)


def down_cooldown_seconds() -> float:
    return _env_float("LAWVER_REDIS_DOWN_COOLDOWN", DEFAULT_DOWN_COOLDOWN_SECONDS)


def mark_down(exc: Optional[BaseException] = None) -> None:
    global _DOWN_UNTIL
    _DOWN_UNTIL = time.time() + down_cooldown_seconds()
    if exc is None:
        _logger.warning("Redis 不可用，已在 %.0f 秒内降级为进程内状态。", down_cooldown_seconds())
    else:
        _logger.warning(
            "Redis 操作失败，已在 %.0f 秒内降级为进程内状态：%s",
            down_cooldown_seconds(),
            exc,
        )


def get_client() -> Optional[Any]:
    """返回可用的 Redis 客户端；未配置、依赖缺失或处于冷却期时返回 None。"""
    global _CLIENT, _CLIENT_URL, _DOWN_UNTIL

    url = redis_url()
    if not url:
        return None
    if time.time() < _DOWN_UNTIL:
        return None
    if _CLIENT is not None and _CLIENT_URL == url:
        return _CLIENT

    with _CLIENT_LOCK:
        if _CLIENT is not None and _CLIENT_URL == url:
            return _CLIENT
        if time.time() < _DOWN_UNTIL:
            return None
        try:
            import redis  # 延迟导入：未安装 redis 时其余功能仍可用。
        except ImportError:
            _logger.info("未安装 redis 依赖，限流与布隆过滤器使用进程内实现。")
            _DOWN_UNTIL = time.time() + down_cooldown_seconds()
            return None

        try:
            client = redis.Redis.from_url(
                url,
                socket_timeout=timeout_seconds(),
                socket_connect_timeout=timeout_seconds(),
                retry_on_timeout=False,
                decode_responses=True,
            )
            client.ping()
        except Exception as exc:  # 配置错误（URL 非法）或连接/认证失败
            mark_down(exc)
            return None

        _CLIENT = client
        _CLIENT_URL = url
        _DOWN_UNTIL = 0.0
        _logger.info("Redis 已连接，限流与布隆过滤器使用共享状态。")
        return _CLIENT


def execute(handler: Callable[[Any], Any], *, default: Any = None, client: Optional[Any] = None) -> Any:
    """在可用客户端上执行操作；任何异常都降级为 default 并触发冷却。"""
    try:
        active = client if client is not None else get_client()
    except Exception as exc:
        mark_down(exc)
        return default
    if active is None:
        return default
    try:
        return handler(active)
    except Exception as exc:
        mark_down(exc)
        return default


def status() -> dict:
    return {
        "configured": is_configured(),
        "available": get_client() is not None,
        "prefix": prefix(),
    }


def reset() -> None:
    """仅供测试：清空缓存客户端与冷却状态。"""
    global _CLIENT, _CLIENT_URL, _DOWN_UNTIL
    client = _CLIENT
    _CLIENT = None
    _CLIENT_URL = None
    _DOWN_UNTIL = 0.0
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
