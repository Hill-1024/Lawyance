"""
模块描述：固定窗口限流器，Redis 可用时跨 worker 共享计数，否则退回进程内计数。

之前 app_security / release_sync 各自维护进程内字典，多 worker 部署时每个 worker
各算各的，真实上限会被放大到 worker 数量倍。这里抽出统一实现：
- Redis：INCR + TTL 原子计数，多 worker / 多实例共享同一个窗口；
- 降级：Redis 未配置或不可用时使用进程内字典，单 worker 行为与旧实现一致。
"""

from __future__ import annotations

import os
import threading
import time
from typing import NamedTuple, Optional

from infra import redis_backend


class RateLimitResult(NamedTuple):
    allowed: bool
    count: int
    limit: int
    retry_after: int

    @property
    def remaining(self) -> int:
        return max(self.limit - self.count, 0)


_LOCAL_LOCK = threading.Lock()
_LOCAL_WINDOWS: dict[tuple[str, str], dict] = {}
_LAST_PRUNE = 0.0
PRUNE_INTERVAL_SECONDS = 60.0


def enabled() -> bool:
    raw = os.getenv("LAWVER_RATE_LIMIT_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _local_counter(scope: str, identifier: str, limit: int, window_seconds: float, now: float) -> RateLimitResult:
    global _LAST_PRUNE
    key = (scope, identifier)
    with _LOCAL_LOCK:
        if now - _LAST_PRUNE > PRUNE_INTERVAL_SECONDS:
            stale = [item for item, data in _LOCAL_WINDOWS.items() if now > data["reset_time"]]
            for item in stale:
                _LOCAL_WINDOWS.pop(item, None)
            _LAST_PRUNE = now

        record = _LOCAL_WINDOWS.get(key)
        if record is None or now > record["reset_time"]:
            _LOCAL_WINDOWS[key] = {"count": 1, "reset_time": now + window_seconds}
            return RateLimitResult(True, 1, limit, int(window_seconds))

        record["count"] += 1
        count = int(record["count"])
        retry_after = max(int(record["reset_time"] - now), 1)
    return RateLimitResult(count <= limit, count, limit, retry_after)


def _redis_counter(scope: str, identifier: str, limit: int, window_seconds: float) -> Optional[RateLimitResult]:
    key = f"{redis_backend.prefix()}:rl:{scope}:{identifier}"

    def handler(client):
        pipe = client.pipeline(transaction=False)
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()
        count = int(count)
        ttl = int(ttl) if ttl is not None else -1
        if ttl < 0:
            # 首次计数（或计数键遗留了丢失的 TTL）时补上过期时间。
            client.expire(key, int(window_seconds))
            ttl = int(window_seconds)
        return RateLimitResult(count <= limit, count, limit, max(ttl, 1))

    return redis_backend.execute(handler)


def hit(
    scope: str,
    identifier: str,
    *,
    limit: int,
    window_seconds: float = 60.0,
    now: Optional[float] = None,
) -> RateLimitResult:
    """消耗一次配额。limit <= 0 表示该桶不限制。"""
    if limit <= 0 or not enabled():
        return RateLimitResult(True, 0, max(limit, 0), 0)

    current = time.time() if now is None else now
    result = _redis_counter(scope, identifier, limit, window_seconds)
    if result is not None:
        return result
    return _local_counter(scope, identifier, limit, window_seconds, current)


def reset(scope: Optional[str] = None) -> None:
    """清空进程内计数；scope 为 None 时全部清空。供测试与运维使用。"""
    with _LOCAL_LOCK:
        if scope is None:
            _LOCAL_WINDOWS.clear()
        else:
            for key in [item for item in _LOCAL_WINDOWS if item[0] == scope]:
                _LOCAL_WINDOWS.pop(key, None)
