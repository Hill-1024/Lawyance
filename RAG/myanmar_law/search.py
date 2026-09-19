"""Search API for the independent Myanmar law corpus.

All public search functions return JSON strings.  Database preparation returns
a dictionary so callers can inspect whether the cache was reused or rebuilt.
Only Python's standard library is required.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
CACHE_DIR = PACKAGE_DIR / "cache"
DB_PATH = CACHE_DIR / "myanmar_law.db"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
SCHEMA_VERSION = 1
MAX_LIMIT = 20
MAX_QUERY_CHARS = 4000

_ENGINE: "MyanmarLawSearchEngine | None" = None
_ENGINE_LOCK = threading.Lock()

_NUMBER_RE = re.compile(
    r"(?i)(?:article|section|rule|chapter|part|order|notification|no\.?)[\s:.-]*"
    r"([0-9၀-၉]+(?:[./-][0-9၀-၉]+)*)"
)
_BARE_LOCATOR_RE = re.compile(r"(?<!\w)([0-9၀-၉]{1,4})(?:\s*[။.])")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def _normalize_locator(value: Any) -> str:
    text = _normalize(value)
    digit_map = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")
    text = text.translate(digit_map)
    text = re.sub(r"(?i)\b(?:article|section|rule|chapter|part)\b", "", text)
    return re.sub(r"[^0-9a-z./-]+", "", text)


def _safe_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(MAX_LIMIT, value))


def _data_files(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.rglob("*.jsonl") if p.is_file())


def _content_fingerprint(data_dir: Path) -> str:
    digest = hashlib.sha256(f"schema:{SCHEMA_VERSION}\n".encode())
    files = _data_files(data_dir)
    if not files:
        raise ValueError(f"Myanmar corpus is missing JSONL files: {data_dir}")
    for path in files:
        digest.update(path.relative_to(data_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _iter_documents(data_dir: Path) -> Iterable[dict[str, Any]]:
    for path in _data_files(data_dir):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL: {path}:{line_number}: {exc}") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"JSONL record must be an object: {path}:{line_number}")
                yield item


def _entry_from_document(document: dict[str, Any], provision: dict[str, Any] | None) -> dict[str, Any]:
    provision = provision or {}
    content = provision.get("original_text") or document.get("content") or ""
    article_number = provision.get("normalized_locator") or provision.get("provision_locator") or ""
    provision_id = str(provision.get("provision_id") or "")
    document_id = str(document.get("document_id") or "")
    rule_id = (
        f"{document_id}:{provision_id}"
        if provision_id
        else document.get("rule_id") or document_id
    )
    page_locator = provision.get("page_locator") or {}
    fields = {
        "rule_id": str(rule_id or ""),
        "source_id": str(document.get("source_id") or ""),
        "law_name": str(document.get("law_name") or ""),
        "article_number": str(article_number),
        "content": str(content),
        "url": str(document.get("url") or ""),
        "status": str(document.get("status") or "unknown"),
        "effective_date": str(document.get("effective_date") or ""),
        "language": str(document.get("language") or ""),
        "country": str(document.get("country") or "MM"),
        "country_label": str(document.get("country_label") or "Myanmar"),
        "jurisdiction": str(document.get("jurisdiction") or "Myanmar"),
        "legal_system": str(document.get("legal_system") or "civil"),
        "legal_hierarchy": str(document.get("legal_hierarchy") or ""),
        "promulgating_body": str(document.get("promulgating_body") or ""),
        "category": str(document.get("category") or ""),
        "subject_matter": str(document.get("subject_matter") or ""),
        "amendment_chain": document.get("amendment_chain") or [],
        "supersedes": document.get("supersedes") or [],
        "document_id": document_id,
        "file_id": str(document.get("file_id") or ""),
        "source_document_url": str(document.get("source_document_url") or ""),
        "source_sha256": str(document.get("source_sha256") or ""),
        "pdf_page_start": page_locator.get("pdf_page_start") or document.get("pdf_page_start"),
        "pdf_page_end": page_locator.get("pdf_page_end") or document.get("pdf_page_end"),
        "text_verification_status": str(
            provision.get("text_verification_status")
            or document.get("text_verification_status")
            or "machine_extracted_unverified"
        ),
        "release_status": str(
            provision.get("release_status") or document.get("release_status") or "review_required"
        ),
        "translation_status": str(document.get("translation_status") or "none"),
        "authority_note": str(
            document.get("authority_note")
            or "Source-language text controls; machine extraction must be checked against the cited source."
        ),
        "provenance": document.get("provenance") or {},
    }
    return fields


def _iter_entries(data_dir: Path) -> Iterable[dict[str, Any]]:
    for document in _iter_documents(data_dir):
        provisions = document.get("provisions") or []
        if provisions:
            for provision in provisions:
                if isinstance(provision, dict):
                    yield _entry_from_document(document, provision)
        else:
            yield _entry_from_document(document, None)


def _public_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result.pop("normalized_title", None)
    result.pop("normalized_article", None)
    result.pop("search_blob", None)
    for name in ("amendment_chain", "supersedes", "provenance"):
        try:
            result[name] = json.loads(result.get(name) or ("{}" if name == "provenance" else "[]"))
        except json.JSONDecodeError:
            result[name] = {} if name == "provenance" else []
    return result


class MyanmarLawSearchEngine:
    def __init__(self, data_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or DATA_DIR)
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self.db_path = self.cache_dir / "myanmar_law.db"
        self.manifest_path = self.cache_dir / "manifest.json"
        self.ensure_ready()

    def ensure_ready(self, *, force_rebuild: bool = False) -> dict[str, Any]:
        fingerprint = _content_fingerprint(self.data_dir)
        if not force_rebuild and self.db_path.exists() and self.manifest_path.exists():
            try:
                manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
            if (
                manifest.get("schema_version") == SCHEMA_VERSION
                and manifest.get("content_sha256") == fingerprint
            ):
                return {
                    "mode": "reuse",
                    "content_sha256": fingerprint,
                    "db_path": str(self.db_path),
                    "schema_version": SCHEMA_VERSION,
                    "document_count": manifest.get("document_count", 0),
                    "entry_count": manifest.get("entry_count", 0),
                }
        return self._rebuild(fingerprint)

    def _rebuild(self, fingerprint: str) -> dict[str, Any]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.cache_dir / "myanmar_law.db.tmp"
        temp_path.unlink(missing_ok=True)
        connection = sqlite3.connect(temp_path)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                CREATE TABLE entries (
                    id INTEGER PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    law_name TEXT NOT NULL,
                    article_number TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    language TEXT NOT NULL,
                    country TEXT NOT NULL,
                    country_label TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    legal_system TEXT NOT NULL,
                    legal_hierarchy TEXT NOT NULL,
                    promulgating_body TEXT NOT NULL,
                    category TEXT NOT NULL,
                    subject_matter TEXT NOT NULL,
                    amendment_chain TEXT NOT NULL,
                    supersedes TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    source_document_url TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    pdf_page_start INTEGER,
                    pdf_page_end INTEGER,
                    text_verification_status TEXT NOT NULL,
                    release_status TEXT NOT NULL,
                    translation_status TEXT NOT NULL,
                    authority_note TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    normalized_article TEXT NOT NULL,
                    search_blob TEXT NOT NULL
                );
                CREATE INDEX idx_entries_exact
                    ON entries(normalized_title, normalized_article);
                CREATE INDEX idx_entries_document ON entries(document_id);
                CREATE INDEX idx_entries_rule ON entries(rule_id);
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )
            entry_count = 0
            document_ids: set[str] = set()
            columns = [
                "rule_id", "source_id", "law_name", "article_number", "content", "url",
                "status", "effective_date", "language", "country", "country_label",
                "jurisdiction", "legal_system", "legal_hierarchy", "promulgating_body",
                "category", "subject_matter", "amendment_chain", "supersedes", "document_id",
                "file_id", "source_document_url", "source_sha256", "pdf_page_start",
                "pdf_page_end", "text_verification_status", "release_status",
                "translation_status", "authority_note", "provenance", "normalized_title",
                "normalized_article", "search_blob",
            ]
            placeholders = ",".join("?" for _ in columns)
            insert_sql = f"INSERT INTO entries ({','.join(columns)}) VALUES ({placeholders})"
            for entry in _iter_entries(self.data_dir):
                if not entry["law_name"] or not entry["content"]:
                    continue
                document_ids.add(entry["document_id"])
                normalized_title = _normalize(entry["law_name"])
                normalized_article = _normalize_locator(entry["article_number"])
                search_blob = _normalize(
                    " ".join(
                        [
                            entry["law_name"], entry["article_number"], entry["content"],
                            entry["category"], entry["subject_matter"], entry["promulgating_body"],
                        ]
                    )
                )
                db_entry = dict(entry)
                db_entry.update(
                    normalized_title=normalized_title,
                    normalized_article=normalized_article,
                    search_blob=search_blob,
                    amendment_chain=json.dumps(entry["amendment_chain"], ensure_ascii=False),
                    supersedes=json.dumps(entry["supersedes"], ensure_ascii=False),
                    provenance=json.dumps(entry["provenance"], ensure_ascii=False),
                )
                connection.execute(insert_sql, [db_entry[name] for name in columns])
                entry_count += 1
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("schema_version", str(SCHEMA_VERSION)),
                    ("content_sha256", fingerprint),
                    ("document_count", str(len(document_ids))),
                    ("entry_count", str(entry_count)),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        temp_path.replace(self.db_path)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "content_sha256": fingerprint,
            "db_path": str(self.db_path),
            "document_count": len(document_ids),
            "entry_count": entry_count,
        }
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"mode": "rebuild", **manifest}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def exact_search(self, title: str, article_number: str) -> str:
        started = time.perf_counter()
        title_key = _normalize(title)
        article_key = _normalize_locator(article_number)
        result: dict[str, Any] = {"success": False, "message": "", "data": None, "search_time": 0.0}
        if not title_key:
            result["message"] = "title 不能为空"
            result["search_time"] = time.perf_counter() - started
            return _json(result)
        with self._connect() as connection:
            if article_key:
                row = connection.execute(
                    "SELECT * FROM entries WHERE normalized_title=? AND normalized_article=? LIMIT 1",
                    (title_key, article_key),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM entries WHERE normalized_title=? ORDER BY id LIMIT 1", (title_key,)
                ).fetchone()
        if row is None:
            result["message"] = "未找到匹配的缅甸法律文本"
        else:
            result.update(success=True, message="找到匹配的缅甸法律文本", data=_public_row(row))
        result["search_time"] = time.perf_counter() - started
        return _json(result)

    def fuzzy_search(self, query: str, limit: int = 5) -> str:
        started = time.perf_counter()
        safe_limit = _safe_limit(limit)
        query_text = _normalize(str(query or "")[:MAX_QUERY_CHARS])
        result: dict[str, Any] = {
            "success": False,
            "message": "",
            "data": [],
            "total_count": 0,
            "returned_count": 0,
            "search_time": 0.0,
        }
        if not query_text:
            result["message"] = "query 不能为空"
            result["search_time"] = time.perf_counter() - started
            return _json(result)
        terms = [term for term in query_text.split(" ") if term] or [query_text]
        where = " OR ".join("search_blob LIKE ?" for _ in terms)
        parameters = [f"%{term}%" for term in terms]
        with self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM entries WHERE {where}", parameters).fetchall()
        scored: list[tuple[int, sqlite3.Row]] = []
        for row in rows:
            blob = row["search_blob"]
            score = sum(blob.count(term) for term in terms)
            if query_text in row["normalized_title"]:
                score += 30
            if query_text == row["normalized_title"]:
                score += 100
            if query_text in row["normalized_article"]:
                score += 10
            scored.append((score, row))
        scored.sort(key=lambda pair: (-pair[0], len(pair[1]["content"]), pair[1]["law_name"]))
        selected = [_public_row(row) for _, row in scored[:safe_limit]]
        result.update(
            success=bool(selected),
            message="找到相关缅甸法律文本" if selected else "未检索到相关缅甸法律文本",
            data=selected,
            total_count=len(scored),
            returned_count=len(selected),
            search_time=time.perf_counter() - started,
        )
        return _json(result)

    semantic_search = fuzzy_search

    def link_search(self, message: str, limit: int = 5) -> str:
        started = time.perf_counter()
        safe_limit = _safe_limit(limit)
        message_text = str(message or "")[:MAX_QUERY_CHARS]
        references: list[dict[str, Any]] = []
        data: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        normalized_message = _normalize(message_text)
        with self._connect() as connection:
            titles = connection.execute(
                "SELECT law_name, normalized_title FROM entries GROUP BY normalized_title"
            ).fetchall()
        locators = [_normalize_locator(value) for value in _NUMBER_RE.findall(message_text)]
        if not locators:
            locators = [_normalize_locator(value) for value in _BARE_LOCATOR_RE.findall(message_text)]
        for title_row in titles:
            if title_row["normalized_title"] not in normalized_message:
                continue
            article = locators[0] if locators else ""
            exact = json.loads(self.exact_search(title_row["law_name"], article))
            if not exact.get("success") and article:
                exact = json.loads(self.exact_search(title_row["law_name"], ""))
            if not exact.get("success"):
                continue
            item = exact["data"]
            key = (item["law_name"], item["article_number"])
            if key in seen:
                continue
            seen.add(key)
            data.append(item)
            if len(data) >= safe_limit:
                break
        if not data and message_text.strip():
            data = json.loads(self.fuzzy_search(message_text, safe_limit)).get("data", [])
        for item in data:
            references.append(
                {
                    "title": item.get("law_name", ""),
                    "article_number": item.get("article_number", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                }
            )
        text = "\n\n".join(
            f"{ref['title']} {ref['article_number']}\n{ref['content']}\n{ref['url']}".strip()
            for ref in references
        )
        return _json(
            {
                "success": bool(references),
                "message": "找到可溯源引用" if references else "未找到可溯源引用",
                "text": text,
                "references": references,
                "data": data,
                "search_time": time.perf_counter() - started,
            }
        )


def _get_engine() -> MyanmarLawSearchEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = MyanmarLawSearchEngine()
        return _ENGINE


def ensure_myanmar_database_ready(*, force_rebuild: bool = False) -> dict[str, Any]:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = MyanmarLawSearchEngine.__new__(MyanmarLawSearchEngine)
            _ENGINE.data_dir = DATA_DIR
            _ENGINE.cache_dir = CACHE_DIR
            _ENGINE.db_path = DB_PATH
            _ENGINE.manifest_path = MANIFEST_PATH
        return _ENGINE.ensure_ready(force_rebuild=force_rebuild)


def exact_search(title: str, article_number: str) -> str:
    return _get_engine().exact_search(title, article_number)


def fuzzy_search(query: str, limit: int = 5) -> str:
    return _get_engine().fuzzy_search(query, limit)


def semantic_search(query: str, limit: int = 5) -> str:
    return _get_engine().fuzzy_search(query, limit)


def link_search(message: str, limit: int = 5) -> str:
    return _get_engine().link_search(message, limit)


def reset_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None
