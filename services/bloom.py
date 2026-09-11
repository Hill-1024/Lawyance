"""
模块描述：布隆过滤器，用极短的位图挡掉「确定不存在」的会话 token，避免无效请求打穿 SQLite。

使用约定（安全性来自这两条不变量）：
- 只增不删：删除会话/账号时不清理位图，宁可多一次回源查询，也绝不误杀有效请求；
- 未就绪即放行：预热未完成、Redis 键被淘汰、命令失败时一律返回「可能存在」，
  让调用方继续走权威存储。布隆过滤器的假阳性只是多查一次库，假阴性才会误杀用户。
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from typing import Any, Iterable, Optional

from services import redis_backend

DEFAULT_ERROR_RATE = 0.001
MIN_BITS = 64


def enabled() -> bool:
    raw = os.getenv("LAWVER_BLOOM_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _parameters(capacity: int, error_rate: float) -> tuple[int, int]:
    capacity = max(int(capacity), 1)
    error_rate = min(max(float(error_rate), 1e-9), 0.5)
    num_bits = max(int(math.ceil(-(capacity * math.log(error_rate)) / (math.log(2) ** 2))), MIN_BITS)
    num_hashes = max(int(round((num_bits / capacity) * math.log(2))), 1)
    return num_bits, num_hashes


def _probe_indexes(item: bytes, num_bits: int, num_hashes: int) -> list[int]:
    digest = hashlib.blake2b(item, digest_size=16).digest()
    first = int.from_bytes(digest[:8], "big")
    second = int.from_bytes(digest[8:], "big") | 1
    return [(first + index * second) % num_bits for index in range(num_hashes)]


def _as_bytes(item: Any) -> bytes:
    if isinstance(item, bytes):
        return item
    return str(item).encode("utf-8")


class LocalBloomFilter:
    """进程内位图实现，单 worker 或未配置 Redis 时使用。"""

    backend = "local"

    def __init__(self, capacity: int, error_rate: float) -> None:
        self.capacity = max(int(capacity), 1)
        self.error_rate = error_rate
        self.num_bits, self.num_hashes = _parameters(self.capacity, error_rate)
        self._bits = bytearray((self.num_bits + 7) // 8)
        self._lock = threading.Lock()
        self._ready = False

    def _set(self, indexes: Iterable[int]) -> int:
        added = 0
        for index in indexes:
            byte_index, bit_index = divmod(index, 8)
            mask = 1 << bit_index
            if not self._bits[byte_index] & mask:
                self._bits[byte_index] |= mask
                added += 1
        return added

    def add(self, item: Any) -> bool:
        indexes = _probe_indexes(_as_bytes(item), self.num_bits, self.num_hashes)
        with self._lock:
            return self._set(indexes) > 0

    def add_many(self, items: Iterable[Any]) -> int:
        count = 0
        for item in items:
            if self.add(item):
                count += 1
        return count

    def maybe_contains(self, item: Any) -> bool:
        if not self._ready:
            return True
        indexes = _probe_indexes(_as_bytes(item), self.num_bits, self.num_hashes)
        with self._lock:
            for index in indexes:
                byte_index, bit_index = divmod(index, 8)
                if not self._bits[byte_index] & (1 << bit_index):
                    return False
        return True

    def warm(self, items: Iterable[Any]) -> int:
        added = self.add_many(items)
        self._ready = True
        return added

    def needs_warm(self) -> bool:
        return not self._ready

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "ready": self._ready,
            "capacity": self.capacity,
            "error_rate": self.error_rate,
            "bits": self.num_bits,
            "hashes": self.num_hashes,
        }


class RedisBloomFilter:
    """共享位图实现：SETBIT/GETBIT 落在 Redis，多 worker 共用同一份过滤器。"""

    backend = "redis"

    def __init__(self, name: str, client: Any, capacity: int, error_rate: float) -> None:
        self.name = name
        self.capacity = max(int(capacity), 1)
        self.error_rate = error_rate
        self.num_bits, self.num_hashes = _parameters(self.capacity, error_rate)
        self._client = client
        self._ready = False
        base = f"{redis_backend.prefix()}:bloom:{name}"
        self._bits_key = base
        self._ready_key = f"{base}:ready"

    def add(self, item: Any) -> bool:
        indexes = _probe_indexes(_as_bytes(item), self.num_bits, self.num_hashes)

        def handler(client):
            pipe = client.pipeline(transaction=False)
            for index in indexes:
                pipe.setbit(self._bits_key, index, 1)
            return pipe.execute()

        return redis_backend.execute(handler, default=None, client=self._client) is not None

    def add_many(self, items: Iterable[Any]) -> int:
        count = 0
        for item in items:
            if self.add(item):
                count += 1
        return count

    def maybe_contains(self, item: Any) -> bool:
        indexes = _probe_indexes(_as_bytes(item), self.num_bits, self.num_hashes)

        def handler(client):
            pipe = client.pipeline(transaction=False)
            pipe.exists(self._bits_key)
            pipe.exists(self._ready_key)
            for index in indexes:
                pipe.getbit(self._bits_key, index)
            return pipe.execute()

        response = redis_backend.execute(handler, default=None, client=self._client)
        if response is None:
            # Redis 故障或未就绪：交给权威存储判断。
            self._ready = False
            return True
        bits_exist, ready_exists = int(response[0]), int(response[1])
        if not bits_exist or not ready_exists:
            # 位图缺失（被淘汰/预热中断）时绝不能判定为「不存在」。
            self._ready = False
            return True
        self._ready = True
        return all(int(bit) for bit in response[2:])

    def warm(self, items: Iterable[Any]) -> int:
        added = self.add_many(items)
        # 就绪标记必须在位图写完后再落，读取端只有在标记与位图同时存在时才信任「不存在」。
        marked = redis_backend.execute(
            lambda client: client.set(self._ready_key, int(time.time())),
            default=None,
            client=self._client,
        )
        if marked is not None:
            self._ready = True
        return added

    def needs_warm(self) -> bool:
        return not self._ready

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "ready": self._ready,
            "capacity": self.capacity,
            "error_rate": self.error_rate,
            "bits": self.num_bits,
            "hashes": self.num_hashes,
            "key": self._bits_key,
        }


class NullBloomFilter:
    """总开关关闭时的空实现：永远返回「可能存在」。"""

    backend = "disabled"
    capacity = 0
    error_rate = 0.0
    num_bits = 0
    num_hashes = 0

    def add(self, item: Any) -> bool:
        return False

    def add_many(self, items: Iterable[Any]) -> int:
        return 0

    def maybe_contains(self, item: Any) -> bool:
        return True

    def warm(self, items: Iterable[Any]) -> int:
        return 0

    def needs_warm(self) -> bool:
        return False

    def status(self) -> dict:
        return {"backend": self.backend, "ready": False}


def create(
    name: str,
    *,
    capacity: int,
    error_rate: float = DEFAULT_ERROR_RATE,
    client: Optional[Any] = None,
) -> LocalBloomFilter | RedisBloomFilter | NullBloomFilter:
    if not enabled():
        return NullBloomFilter()
    if client is None:
        client = redis_backend.get_client()
    if client is not None:
        return RedisBloomFilter(name, client, capacity, error_rate)
    return LocalBloomFilter(capacity, error_rate)
