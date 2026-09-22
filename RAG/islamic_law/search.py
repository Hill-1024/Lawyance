"""
模块描述：伊斯兰法系检索引擎（schema v3 双层库）。
默认数据库：cache/islamic_rules.db
- 转化层 islamic_rules 为主检索对象
- 命中后按 sharia_principle_id 附带共享层摘要
提供 exact_search / semantic_search(=fuzzy_search) / link_search / rules_by_principle。
检索 envelope 对齐主库 RAG/law_data_search.py；领域仍保持双层模型。
不修改 tools/__init__.py、mcps.py、function_calling.py。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Optional

from .countries import COUNTRY_LABELS, country_display_name
from .models import IslamicRule, ShariaPrinciple

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
SCHEMA_PATH = BASE_DIR / "schema.sql"
DB_PATH = CACHE_DIR / "islamic_rules.db"
MANIFEST_SHARED = CACHE_DIR / "manifest.shared.json"
MANIFEST_BUILD = CACHE_DIR / "manifest.build.json"
SCHEMA_VERSION = 3

MAX_QUERY_CHARS = 4000
MAX_SEARCH_LIMIT = 20
MAX_TITLE_CHARS = 240
MAX_ARTICLE_CHARS = 120

BUILD_LOCK = threading.Lock()
_ENGINE: Optional["IslamicLawSearchEngine"] = None
_ENGINE_LOCK = threading.Lock()

ARTICLE_HINT_RE = re.compile(
    r"(?P<label>(?:Section|Article|Art\.?|Seksyen|Pasal|المادة)\s*)"
    r"(?P<num>[0-9]+(?:\s*[A-Za-z])?)",
    re.IGNORECASE,
)
QUOTED_LAW_RE = re.compile(r"[\"「《]([^\"」》]{3,120})[\"」》]")


def trim_text(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def normalize_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, MAX_SEARCH_LIMIT))


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_key(text: str) -> str:
    text = normalize_whitespace(text).lower()
    text = text.replace("《", "").replace("》", "")
    return re.sub(r"[\s\-—_·•:：,，.。/\\()'\"“”‘’]+", "", text)


def normalize_article_key(article_number: str) -> str:
    text = normalize_whitespace(article_number)
    # 已是显式 article_key（如 MY-RIBA-FORMAL / ID-HALAL-UU33-FORMAL）时直接保留
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"[A-Za-z]{2}-[A-Za-z0-9\-]+", compact):
        return compact.upper()
    match = ARTICLE_HINT_RE.search(text)
    if match:
        return re.sub(r"\s+", "", match.group("num")).upper()
    digits = re.findall(r"[0-9]+[A-Za-z]?", text)
    if digits:
        return digits[0].upper()
    return normalize_key(text)


def article_key_candidates(article_number: str) -> list[str]:
    """exact 查询时尝试多种 article_key，避免 Formal 条目被抽成 Section 数字误命中。"""
    text = normalize_whitespace(article_number)
    keys: list[str] = []
    for candidate in (
        normalize_article_key(text),
        re.sub(r"\s+", "", text).upper(),
        normalize_key(text),
    ):
        if candidate and candidate not in keys:
            keys.append(candidate)
    return keys


def build_query_terms(query: str) -> list[str]:
    raw = normalize_whitespace(query).lower()
    parts = re.split(r"[\s,，;/|]+", raw)
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        token = part.strip()
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) >= 32:
            break
    return terms


def score_item(blob: str, query: str, terms: Iterable[str]) -> int:
    compact_blob = normalize_key(blob)
    compact_query = normalize_key(query)
    score = 0
    matched = 0
    if compact_query and compact_query in compact_blob:
        score += 40
    for term in terms:
        compact_term = normalize_key(term)
        if len(compact_term) < 2:
            continue
        count = compact_blob.count(compact_term)
        if not count:
            continue
        matched += 1
        score += 8 + min(count, 3) * 2
    if matched:
        score += matched * 10
    return score


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_manifest() -> dict[str, Any]:
    """
    对齐主库「语料指纹 → 是否重建」思路。
    指纹覆盖 schema.sql + data/ 下全部 JSON（不扫 sources/ 大 PDF）。
    """
    data_root = BASE_DIR / "data"
    files: dict[str, dict[str, Any]] = {}
    digest = hashlib.sha256()
    digest.update(f"schema:{SCHEMA_VERSION}\n".encode("utf-8"))

    paths = [SCHEMA_PATH]
    if data_root.is_dir():
        paths.extend(sorted(data_root.rglob("*.json")))
    for path in paths:
        relative = str(path.relative_to(BASE_DIR)).replace("\\", "/")
        file_sha = _hash_file(path)
        stat = path.stat()
        files[relative] = {
            "size": stat.st_size,
            "sha256": file_sha,
        }
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha.encode("ascii"))
        digest.update(b"\0")

    return {
        "schema_version": SCHEMA_VERSION,
        "file_count": len(files),
        "content_sha256": digest.hexdigest(),
        "files": files,
    }


def _read_build_manifest() -> dict[str, Any] | None:
    if not MANIFEST_BUILD.exists():
        return None
    try:
        payload = json.loads(MANIFEST_BUILD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _needs_rebuild(source_manifest: dict[str, Any]) -> bool:
    if not DB_PATH.exists():
        return True
    current = _read_build_manifest()
    if current is None:
        return True
    return (
        current.get("schema_version") != source_manifest.get("schema_version")
        or current.get("content_sha256") != source_manifest.get("content_sha256")
    )


def ensure_islamic_database_ready(*, force_rebuild: bool = False) -> dict[str, Any]:
    """确保规则库存在；语料指纹变化、缺表/空表或 force 时执行种子重建。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    source_manifest = build_source_manifest()
    needs_seed = force_rebuild or _needs_rebuild(source_manifest)

    if not needs_seed:
        try:
            with closing(sqlite3.connect(DB_PATH)) as conn:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                required = {"islamic_rules", "sharia_principles", "terminology"}
                if not required.issubset(tables):
                    needs_seed = True
                else:
                    n = conn.execute("SELECT COUNT(*) FROM islamic_rules").fetchone()[0]
                    if n == 0:
                        needs_seed = True
        except sqlite3.Error:
            needs_seed = True

    if needs_seed:
        from .scripts.insert_riba_sample import main as seed_main

        seed_main()
        MANIFEST_BUILD.write_text(
            json.dumps(source_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "mode": "seed",
            "schema_version": SCHEMA_VERSION,
            "db_path": str(DB_PATH),
            "content_sha256": source_manifest["content_sha256"],
        }

    shared_meta = {}
    if MANIFEST_SHARED.exists():
        try:
            shared_meta = json.loads(MANIFEST_SHARED.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            shared_meta = {}
    return {
        "mode": "reuse",
        "schema_version": shared_meta.get("schema_version", SCHEMA_VERSION),
        "db_path": str(DB_PATH),
        "content_sha256": source_manifest["content_sha256"],
    }


class IslamicLawSearchEngine:
    def __init__(self) -> None:
        with BUILD_LOCK:
            ensure_islamic_database_ready()
        if not DB_PATH.exists():
            raise ValueError(f"Islamic rules database missing: {DB_PATH}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _load_principle(self, conn: sqlite3.Connection, principle_id: str) -> ShariaPrinciple | None:
        if not principle_id:
            return None
        row = conn.execute(
            "SELECT * FROM sharia_principles WHERE sharia_principle_id = ?",
            (principle_id,),
        ).fetchone()
        if row is None:
            return None
        return ShariaPrinciple.from_row(row)

    def _result_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        rule = IslamicRule.from_row(row)
        principle = self._load_principle(conn, rule.sharia_principle_id)
        return rule.to_canonical_result(principle)

    def exact_search(self, title: str, article_number: str) -> str:
        start = time.time()
        title = trim_text(title, MAX_TITLE_CHARS)
        article_number = trim_text(article_number, MAX_ARTICLE_CHARS)
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "data": None,
            "search_time": 0.0,
        }
        if not title or not article_number:
            result["message"] = "law_name and article_number are required"
            result["search_time"] = time.time() - start
            return json.dumps(result, ensure_ascii=False)

        title_key = normalize_key(title)
        key_candidates = article_key_candidates(article_number)
        with closing(self._connect()) as conn:
            row = None
            for article_key in key_candidates:
                row = conn.execute(
                    """
                    SELECT * FROM islamic_rules
                    WHERE law_name_key = ? AND article_key = ?
                      AND status != 'repealed'
                    ORDER BY CASE status WHEN 'in_force' THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (title_key, article_key),
                ).fetchone()
                if row is not None:
                    break
            if row is None:
                for article_key in key_candidates:
                    row = conn.execute(
                        """
                        SELECT * FROM islamic_rules
                        WHERE (instr(law_name_key, ?) > 0 OR instr(?, law_name_key) > 0)
                          AND article_key = ?
                          AND length(?) >= 4
                          AND status != 'repealed'
                        ORDER BY length(law_name_key) ASC
                        LIMIT 1
                        """,
                        (title_key, title_key, article_key, title_key),
                    ).fetchone()
                    if row is not None:
                        break
            if row is None:
                result["message"] = f"No article found for {title!r} / {article_number!r}"
                result["search_time"] = time.time() - start
                return json.dumps(result, ensure_ascii=False)

            result["success"] = True
            result["message"] = "ok"
            result["data"] = self._result_from_row(conn, row)
            result["search_time"] = time.time() - start
            return json.dumps(result, ensure_ascii=False)

    def semantic_search(self, query: str, limit: int = 5) -> str:
        start = time.time()
        safe_limit = normalize_limit(limit)
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "data": [],
            "total_count": 0,
            "returned_count": 0,
            "search_time": 0.0,
        }
        query = normalize_whitespace(trim_text(query, MAX_QUERY_CHARS))
        if not query:
            result["message"] = "query is required"
            result["search_time"] = time.time() - start
            return json.dumps(result, ensure_ascii=False)

        terms = build_query_terms(query)
        country_filter = None
        upper = query.upper()
        lowered = query.lower()
        # 中文/别名优先，避免仅依赖英文国名
        _country_aliases = {
            "ID": ("indonesia", "印度尼西亚", "印尼"),
            "MY": ("malaysia", "马来西亚"),
            "BN": ("brunei", "文莱"),
            "SG": ("singapore", "新加坡"),
            "PH": ("philippines", "菲律宾"),
            "TH": ("thailand", "泰国"),
            "VN": ("vietnam", "越南"),
            "MM": ("myanmar", "缅甸"),
        }
        for code, aliases in _country_aliases.items():
            if re.search(rf"\b{code}\b", upper) or any(a in lowered or a in query for a in aliases):
                country_filter = code
                break
        if country_filter is None:
            for code, label in COUNTRY_LABELS.items():
                if re.search(rf"\b{code}\b", upper) or label.lower() in lowered:
                    country_filter = code
                    break

        candidates: list[tuple[int, dict[str, Any]]] = []
        with closing(self._connect()) as conn:
            sql = "SELECT * FROM islamic_rules WHERE status != 'repealed'"
            params: list[Any] = []
            if country_filter:
                sql += " AND country = ?"
                params.append(country_filter)
            for row in conn.execute(sql, params):
                score = score_item(row["search_blob"], query, terms)
                # 共享层主题也可加分
                if row["sharia_principle_id"]:
                    principle = self._load_principle(conn, row["sharia_principle_id"])
                    if principle is not None:
                        score += score_item(principle.search_blob, query, terms) // 2
                if score <= 0:
                    continue
                candidates.append((score, self._result_from_row(conn, row)))

            # 共享层原则始终参与语义检索（religious-guidance，不得单独当合规结论）
            for row in conn.execute("SELECT * FROM sharia_principles"):
                score = score_item(row["search_blob"], query, terms)
                if score <= 0:
                    continue
                principle = ShariaPrinciple.from_row(row)
                summary = {
                    "law_name": f"[shared principle] {principle.rule_subject}",
                    "article_number": principle.religious_anchor or principle.sharia_source_type,
                    "content": principle.content,
                    "url": principle.url,
                    "source_id": principle.sharia_principle_id,
                    "status": "unknown",
                    "effective_date": "",
                    "language": "ar",
                    "country": "XX",
                    "country_label": country_display_name("XX"),
                    "legal_system": "islamic",
                    "legal_effect": principle.legal_effect,
                    "sharia_principle_id": principle.sharia_principle_id,
                    "madhhab": principle.madhhab,
                    "principle": principle.to_summary(),
                    "note": "Shared religious layer only; not a country binding rule.",
                }
                candidates.append((score, summary))

        candidates.sort(key=lambda item: (-item[0], len(str(item[1].get("law_name", "")))))
        selected = [item for _, item in candidates[:safe_limit]]
        result["success"] = bool(selected)
        result["message"] = "ok" if selected else "No matching Islamic-law articles"
        result["data"] = selected
        result["total_count"] = len(candidates)
        result["returned_count"] = len(selected)
        result["search_time"] = time.time() - start
        return json.dumps(result, ensure_ascii=False)

    def link_search(self, message: str, limit: int = 5) -> str:
        start = time.time()
        safe_limit = normalize_limit(limit)
        message = trim_text(message, MAX_QUERY_CHARS)
        references: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        quoted_titles = QUOTED_LAW_RE.findall(message)
        article_matches = list(ARTICLE_HINT_RE.finditer(message))

        for title in quoted_titles:
            for match in article_matches:
                exact = json.loads(self.exact_search(title, match.group(0)))
                if not exact.get("success"):
                    continue
                data = exact.get("data") or {}
                key = (
                    data.get("country", ""),
                    data.get("law_name", ""),
                    data.get("article_number", ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                references.append(data)
                if len(references) >= safe_limit:
                    break
            if len(references) >= safe_limit:
                break

        if len(references) < safe_limit:
            fuzzy = json.loads(self.semantic_search(message, safe_limit))
            for item in fuzzy.get("data") or []:
                key = (
                    item.get("country", ""),
                    item.get("law_name", ""),
                    item.get("article_number", ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                references.append(item)
                if len(references) >= safe_limit:
                    break

        lines = []
        for index, item in enumerate(references, start=1):
            country = item.get("country") or ""
            label = item.get("country_label") or country
            effect = item.get("legal_effect") or ""
            principle_id = item.get("sharia_principle_id") or ""
            prefix = (
                f"{index}. [{country}/{label}] 《{item.get('law_name', '')}》"
                f"{item.get('article_number', '')}"
            ).strip()
            if effect:
                prefix += f" ({effect})"
            if principle_id:
                prefix += f" ↔ {principle_id}"
            url = item.get("url") or ""
            lines.append(f"{prefix}: {url}" if url else prefix)

        return json.dumps(
            {
                "success": bool(references),
                "message": "ok" if references else "No linkable references found",
                # 兼容本库既有消费者：完整 canonical 放 data
                "data": references,
                # 对齐主库 law_link_search：另给精简 references
                "references": [
                    {
                        "title": item.get("law_name", ""),
                        "article_number": item.get("article_number", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", ""),
                    }
                    for item in references
                ],
                "text": "\n".join(lines),
                "search_time": time.time() - start,
            },
            ensure_ascii=False,
        )

    def rules_by_principle(
        self,
        principle_id: str,
        country: str | None = None,
        limit: int = 100,
    ) -> str:
        """
        按共享层原则 ID 反查各国转化实例（4.3）。
        返回原则摘要 + 实例列表，并按 country 分组。
        """
        start = time.time()
        pid = normalize_whitespace(principle_id)
        country_code = normalize_whitespace(country or "").upper() or None
        try:
            safe_limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            safe_limit = 100
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "sharia_principle_id": pid,
            "principle": None,
            "data": [],
            "by_country": {},
            "total_count": 0,
            "returned_count": 0,
            "search_time": 0.0,
        }
        if not pid:
            result["message"] = "sharia_principle_id is required"
            result["search_time"] = time.time() - start
            return json.dumps(result, ensure_ascii=False)

        with closing(self._connect()) as conn:
            principle = self._load_principle(conn, pid)
            if principle is None:
                result["message"] = f"principle not found: {pid}"
                result["search_time"] = time.time() - start
                return json.dumps(result, ensure_ascii=False)

            sql = """
                SELECT * FROM islamic_rules
                WHERE sharia_principle_id = ?
                  AND status != 'repealed'
            """
            params: list[Any] = [pid]
            if country_code:
                sql += " AND country = ?"
                params.append(country_code)
            sql += " ORDER BY country ASC, rule_id ASC"
            rows = conn.execute(sql, params).fetchall()

            items = [self._result_from_row(conn, row) for row in rows]
            by_country: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                code = str(item.get("country") or "")
                by_country.setdefault(code, []).append(item)

            # 与原则侧 country_rule_ids 交叉核对（完整性）
            reverse_ids = set(principle.country_rule_ids)
            db_ids = {item.get("rule_id") for item in items}
            missing_in_db = sorted(reverse_ids - db_ids)
            if country_code:
                missing_in_db = [rid for rid in missing_in_db if rid.startswith(f"{country_code}-")]

            result["success"] = True
            result["message"] = "ok"
            result["principle"] = principle.to_summary()
            result["data"] = items[:safe_limit]
            result["by_country"] = {
                code: group[:safe_limit] for code, group in by_country.items()
            }
            result["total_count"] = len(items)
            result["returned_count"] = len(result["data"])
            result["country_rule_ids"] = list(principle.country_rule_ids)
            result["missing_from_db"] = missing_in_db
            result["search_time"] = time.time() - start
            return json.dumps(result, ensure_ascii=False)


def get_engine() -> IslamicLawSearchEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = IslamicLawSearchEngine()
    return _ENGINE


def reset_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None


def exact_search(title: str, article_number: str) -> str:
    return get_engine().exact_search(title, article_number)


def semantic_search(query: str, limit: int = 5) -> str:
    """关键词模糊检索（实现同主库 fuzzy_search；保留 semantic_search 旧名）。"""
    return get_engine().semantic_search(query, limit)


def fuzzy_search(query: str, limit: int = 5) -> str:
    """对齐主库命名：fuzzy_search == semantic_search。"""
    return semantic_search(query, limit)


def link_search(message: str, limit: int = 5) -> str:
    return get_engine().link_search(message, limit)


def rules_by_principle(
    principle_id: str,
    country: str | None = None,
    limit: int = 100,
) -> str:
    """按 SH-PRINCIPLE-* 反查各国转化实例（含 by_country 分组）。"""
    return get_engine().rules_by_principle(principle_id, country=country, limit=limit)
