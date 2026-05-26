"""
模块描述：结构化日志。
记录文书生成的完整生命周期，generation_id 串联全链路。
"""

from __future__ import annotations

import logging
import time
import uuid

from .errors import LegalDocumentError

_logger = logging.getLogger("legal_document")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s | %(message)s"))
    _logger.addHandler(_handler)


def get_logger() -> logging.Logger:
    return _logger


def _make_generation_id() -> str:
    return uuid.uuid4().hex[:12]


def log_template_cache_hit(template_name: str) -> None:
    _logger.debug("Cache HIT | template=%s", template_name)


def log_template_cache_miss(template_name: str) -> None:
    _logger.debug("Cache MISS | template=%s", template_name)


def log_template_cache_refresh(template_name: str) -> None:
    _logger.debug("Cache REFRESH (mtime changed) | template=%s", template_name)


def log_template_syntax_warnings(template_name: str, warnings: list[str]) -> None:
    for w in warnings:
        _logger.warning("Template syntax warning | template=%s | %s", template_name, w)


def log_generation_start(template_name: str, field_count: int) -> str:
    gid = _make_generation_id()
    _logger.info(
        "Generation START | generation_id=%s | template=%s | field_count=%d | timestamp=%.3f",
        gid, template_name, field_count, time.time())
    return gid


def log_generation_complete(generation_id: str, duration_ms: float, output_path: str, cache_hit: bool = True) -> None:
    _logger.info(
        "Generation COMPLETE | generation_id=%s | duration_ms=%.1f | cache_hit=%s | output_path=%s",
        generation_id, duration_ms, cache_hit, output_path)


def log_generation_error(generation_id: str, error: LegalDocumentError, duration_ms: float) -> None:
    _logger.error(
        "Generation ERROR | generation_id=%s | duration_ms=%.1f | error_code=%s | error_message=%s",
        generation_id, duration_ms, error.code, error.message)
