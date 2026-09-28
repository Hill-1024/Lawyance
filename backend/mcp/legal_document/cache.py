"""
模块描述：写作守则（guide）缓存。
线程安全的单例缓存，基于 guide JSON 文件 mtime 自动热更新。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import ManifestValidationError, TemplateNotFoundError
from .validator import load_and_validate_guide


_GUIDES_DIR = Path(__file__).resolve().parent / "guides"


@dataclass
class _CachedGuide:
    guide: dict
    loaded_at: float
    mtime: float


@dataclass
class GuideIndexEntry:
    doc_type: str
    category: str
    description: str
    required_sections: list[str]
    applicable_law: list[str]


class GuideCache:
    """线程安全的 guide 缓存。基于 JSON 文件 mtime 自动热更新，LRU 淘汰。"""

    def __init__(self, max_size: int = 32):
        self._max_size = max_size
        self._lock = threading.RLock()
        self._cache: dict[str, _CachedGuide] = {}
        self._index: list[GuideIndexEntry] | None = None
        self._index_mtime: float = 0.0

    def _guide_path(self, doc_type: str) -> Path:
        return _GUIDES_DIR / "{}.json".format(doc_type)

    def _load(self, doc_type: str) -> _CachedGuide:
        path = self._guide_path(doc_type)
        guide = load_and_validate_guide(str(path))
        mtime = os.path.getmtime(path)
        return _CachedGuide(guide=guide, loaded_at=time.time(), mtime=mtime)

    def _evict_lru(self) -> None:
        if len(self._cache) >= self._max_size:
            oldest = min(self._cache, key=lambda k: self._cache[k].loaded_at)
            del self._cache[oldest]

    def get(self, doc_type: str) -> dict:
        """获取 guide。命中且 mtime 未变 → 返回缓存；变更 → 重新加载。"""
        with self._lock:
            name = doc_type.strip()
            path = self._guide_path(name)
            if not path.is_file():
                raise TemplateNotFoundError(name, self._list_doc_types())
            current_mtime = os.path.getmtime(path)
            if name in self._cache and self._cache[name].mtime == current_mtime:
                return self._cache[name].guide
            cached = self._load(name)
            if name in self._cache:
                self._cache[name] = cached
            else:
                self._evict_lru()
                self._cache[name] = cached
            return cached.guide

    def get_index(self) -> list[GuideIndexEntry]:
        """获取所有 guide 索引摘要（缓存结果，目录变更时自动刷新）。"""
        with self._lock:
            guides_dir_mtime = 0.0
            if _GUIDES_DIR.is_dir():
                guides_dir_mtime = os.path.getmtime(_GUIDES_DIR)
                for child in _GUIDES_DIR.iterdir():
                    if child.is_file() and child.suffix == ".json":
                        try:
                            tm = os.path.getmtime(child)
                            if tm > guides_dir_mtime:
                                guides_dir_mtime = tm
                        except OSError:
                            pass
            if self._index is not None and guides_dir_mtime <= self._index_mtime:
                return self._index
            index: list[GuideIndexEntry] = []
            if _GUIDES_DIR.is_dir():
                for child in sorted(_GUIDES_DIR.iterdir()):
                    if not child.is_file() or child.suffix != ".json":
                        continue
                    try:
                        guide = load_and_validate_guide(str(child))
                        index.append(GuideIndexEntry(
                            doc_type=guide["doc_type"],
                            category=guide["category"],
                            description=guide["description"],
                            required_sections=guide["required_sections"],
                            applicable_law=guide["applicable_law"],
                        ))
                    except ManifestValidationError:
                        continue
            self._index = index
            self._index_mtime = guides_dir_mtime
            return index

    def invalidate(self, doc_type: str) -> None:
        with self._lock:
            self._cache.pop(doc_type.strip(), None)

    def warm_all(self) -> int:
        count = 0
        for entry in self.get_index():
            try:
                self.get(entry.doc_type)
                count += 1
            except Exception:
                pass
        return count

    def _list_doc_types(self) -> list[str]:
        return [e.doc_type for e in self.get_index()]


guide_cache = GuideCache(max_size=32)
