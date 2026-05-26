"""
模块描述：模板缓存。
线程安全的单例缓存，基于文件 mtime 自动热更新。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from docxtpl import DocxTemplate

from .errors import ManifestValidationError, TemplateNotFoundError
from .validator import load_and_validate_manifest

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


@dataclass
class _CachedTemplate:
    manifest: dict
    docx: DocxTemplate
    loaded_at: float
    mtime: float


@dataclass
class TemplateIndexEntry:
    name: str
    version: str
    category: str
    description: str
    field_count: int
    field_keys: list[str]


class TemplateCache:
    """线程安全的模板缓存。基于文件 mtime 自动热更新，LRU 淘汰。"""

    def __init__(self, max_size: int = 32):
        self._max_size = max_size
        self._lock = threading.RLock()
        self._cache: dict[str, _CachedTemplate] = {}
        self._index: list[TemplateIndexEntry] | None = None
        self._index_mtime: float = 0.0

    def _template_dir(self, name: str) -> Path:
        return _TEMPLATES_DIR / name

    def _load_manifest(self, name: str) -> dict:
        manifest_path = self._template_dir(name) / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("manifest.json 不存在: {}".format(manifest_path))
        return load_and_validate_manifest(str(manifest_path))

    def _load_docx(self, name: str) -> DocxTemplate:
        docx_path = self._template_dir(name) / "template.docx"
        if not docx_path.is_file():
            raise FileNotFoundError("template.docx 不存在: {}".format(docx_path))
        return DocxTemplate(str(docx_path))

    def _load(self, name: str) -> _CachedTemplate:
        manifest = self._load_manifest(name)
        docx = self._load_docx(name)
        docx_mtime = os.path.getmtime(self._template_dir(name) / "template.docx")
        return _CachedTemplate(manifest=manifest, docx=docx, loaded_at=time.time(), mtime=docx_mtime)

    def _evict_lru(self) -> None:
        if len(self._cache) >= self._max_size:
            oldest = min(self._cache, key=lambda k: self._cache[k].loaded_at)
            del self._cache[oldest]

    def get(self, template_name: str) -> _CachedTemplate:
        """获取模板。缓存命中且 mtime 未变 → 直接返回；mtime 变更 → 重新加载。"""
        with self._lock:
            name = template_name.strip()
            template_dir = self._template_dir(name)
            if not template_dir.is_dir():
                raise TemplateNotFoundError(name, self._list_template_names())
            docx_path = template_dir / "template.docx"
            if not docx_path.is_file():
                raise TemplateNotFoundError(name, self._list_template_names())
            current_mtime = os.path.getmtime(docx_path)
            if name in self._cache:
                cached = self._cache[name]
                if cached.mtime == current_mtime:
                    return cached
            cached = self._load(name)
            if name in self._cache:
                self._cache[name] = cached
            else:
                self._evict_lru()
                self._cache[name] = cached
            return cached

    def get_index(self) -> list[TemplateIndexEntry]:
        """获取所有模板索引摘要（缓存结果，目录变更时自动刷新）。"""
        with self._lock:
            templates_dir_mtime = 0.0
            if _TEMPLATES_DIR.is_dir():
                templates_dir_mtime = os.path.getmtime(_TEMPLATES_DIR)
                for child in _TEMPLATES_DIR.iterdir():
                    if child.is_dir():
                        try:
                            tm = os.path.getmtime(child)
                            if tm > templates_dir_mtime:
                                templates_dir_mtime = tm
                        except OSError:
                            pass
            if self._index is not None and templates_dir_mtime <= self._index_mtime:
                return self._index
            index: list[TemplateIndexEntry] = []
            if _TEMPLATES_DIR.is_dir():
                for child in sorted(_TEMPLATES_DIR.iterdir()):
                    if not child.is_dir():
                        continue
                    manifest_path = child / "manifest.json"
                    docx_path = child / "template.docx"
                    if not manifest_path.is_file() or not docx_path.is_file():
                        continue
                    try:
                        manifest = load_and_validate_manifest(str(manifest_path))
                        index.append(TemplateIndexEntry(
                            name=manifest["name"],
                            version=manifest["version"],
                            category=manifest["category"],
                            description=manifest["description"],
                            field_count=len(manifest["fields"]),
                            field_keys=[f["key"] for f in manifest["fields"]],
                        ))
                    except ManifestValidationError:
                        continue
            self._index = index
            self._index_mtime = templates_dir_mtime
            return index

    def invalidate(self, template_name: str) -> None:
        with self._lock:
            self._cache.pop(template_name.strip(), None)

    def warm_all(self) -> int:
        count = 0
        for entry in self.get_index():
            try:
                self.get(entry.name)
                count += 1
            except Exception:
                pass
        return count

    def _list_template_names(self) -> list[str]:
        return [e.name for e in self.get_index()]


template_cache = TemplateCache(max_size=32)
