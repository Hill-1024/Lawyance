"""SQLite-backed retrieval API for the Singapore written-law corpus.

This module deliberately does not register any LLM tools.  It only exposes
the jurisdiction-level Python API requested by the database coordination
protocol.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


PACKAGE_DIR = Path(__file__).resolve().parent
DATA_PATH = Path(
    os.environ.get(
        "SINGAPORE_LAW_DATA_PATH",
        str(PACKAGE_DIR / "data" / "official_seed.json"),
    )
)
CACHE_DIR = Path(
    os.environ.get(
        "SINGAPORE_LAW_CACHE_DIR",
        str(PACKAGE_DIR / "cache"),
    )
)
DB_PATH = CACHE_DIR / "singapore_law.db"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
SCHEMA_VERSION = "1.0.0"

_BUILD_LOCK = threading.RLock()
_ENGINE_LOCK = threading.Lock()
_ENGINE: Optional["SingaporeLawSearchEngine"] = None

_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^0-9a-z\u3400-\u9fff]+")
_ARTICLE_PREFIX_RE = re.compile(
    r"^(?:section|sec\.?|s\.?|article|art\.?)\s*", re.IGNORECASE
)
_EN_SECTION_RE = re.compile(
    r"\b(?:section|sec\.?|s\.?)\s*(\d+[A-Za-z]?(?:\([0-9A-Za-z]+\))*)",
    re.IGNORECASE,
)
_ZH_SECTION_RE = re.compile(r"第\s*(\d+[A-Za-z]?)\s*条")


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = _NON_WORD_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _normalize_article_number(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = _ARTICLE_PREFIX_RE.sub("", text)
    if text.startswith("第") and text.endswith("条"):
        text = text[1:-1]
    return re.sub(r"\s+", "", text).casefold()


def _clamp_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 5
    return max(1, min(value, 20))


def _source_manifest() -> Dict[str, object]:
    raw = DATA_PATH.read_bytes()
    digest = hashlib.sha256()
    digest.update(SCHEMA_VERSION.encode("utf-8"))
    digest.update(b"\0")
    digest.update(raw)
    records = json.loads(raw.decode("utf-8"))
    if not isinstance(records, list):
        raise ValueError("official_seed.json must contain a JSON array")
    return {
        "schema_version": SCHEMA_VERSION,
        "content_sha256": digest.hexdigest(),
        "record_count": len(records),
        "data_path": str(DATA_PATH),
    }


def _read_cached_manifest() -> Optional[Dict[str, object]]:
    if not MANIFEST_PATH.exists():
        return None
    try:
        value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _validate_record(record: Dict[str, Any], index: int) -> None:
    required = ("rule_id", "law_name", "article_number", "content", "url")
    missing = [key for key in required if key not in record]
    if missing:
        raise ValueError(f"seed record {index} is missing fields: {', '.join(missing)}")
    for key in ("rule_id", "law_name", "article_number", "content"):
        if not str(record.get(key, "")).strip():
            raise ValueError(f"seed record {index} has an empty {key}")
    if record.get("language") != "en":
        raise ValueError(f"seed record {index} must identify authoritative language as en")
    if record.get("legal_system") != "common":
        raise ValueError(f"seed record {index} must identify legal_system as common")


def _search_blob(record: Dict[str, Any]) -> str:
    fields = (
        "law_name",
        "article_number",
        "article_title",
        "content",
        "topic_zh",
        "citation",
        "subject_matter",
        "gazette_number",
    )
    return "\n".join(str(record.get(key, "")) for key in fields)


def _build_database(records: Sequence[Dict[str, Any]], destination: Path) -> None:
    if destination.exists():
        destination.unlink()
    conn = sqlite3.connect(destination)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(
            """
            CREATE TABLE records (
                rule_id TEXT PRIMARY KEY,
                law_name TEXT NOT NULL,
                normalized_law_name TEXT NOT NULL,
                article_number TEXT NOT NULL,
                normalized_article_number TEXT NOT NULL,
                content TEXT NOT NULL,
                url TEXT NOT NULL,
                topic_zh TEXT NOT NULL,
                citation TEXT NOT NULL,
                year INTEGER,
                status TEXT NOT NULL,
                search_blob TEXT NOT NULL,
                normalized_search_blob TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX idx_records_exact
                ON records(normalized_law_name, normalized_article_number);
            CREATE INDEX idx_records_citation ON records(citation);
            CREATE INDEX idx_records_year ON records(year);
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE records_fts USING fts5(
                    rule_id UNINDEXED,
                    law_name,
                    article_number,
                    article_title,
                    content,
                    topic_zh,
                    citation,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            fts_enabled = True
        except sqlite3.OperationalError:
            fts_enabled = False

        rows = []
        fts_rows = []
        for index, raw in enumerate(records):
            if not isinstance(raw, dict):
                raise ValueError(f"seed record {index} must be a JSON object")
            record = dict(raw)
            _validate_record(record, index)
            blob = _search_blob(record)
            rows.append(
                (
                    str(record["rule_id"]),
                    str(record["law_name"]),
                    _normalize_text(record["law_name"]),
                    str(record["article_number"]),
                    _normalize_article_number(record["article_number"]),
                    str(record["content"]),
                    str(record["url"]),
                    str(record.get("topic_zh", "")),
                    str(record.get("citation", "")),
                    int(record["year"]) if record.get("year") not in (None, "") else None,
                    str(record.get("status", "unknown")),
                    blob,
                    _normalize_text(blob),
                    _json_dumps(record),
                )
            )
            fts_rows.append(
                (
                    str(record["rule_id"]),
                    str(record["law_name"]),
                    str(record["article_number"]),
                    str(record.get("article_title", "")),
                    str(record["content"]),
                    str(record.get("topic_zh", "")),
                    str(record.get("citation", "")),
                )
            )

        conn.executemany(
            """
            INSERT INTO records (
                rule_id, law_name, normalized_law_name, article_number,
                normalized_article_number, content, url, topic_zh,
                citation, year, status, search_blob, normalized_search_blob,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        if fts_enabled:
            conn.executemany(
                """
                INSERT INTO records_fts (
                    rule_id, law_name, article_number, article_title,
                    content, topic_zh, citation
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                fts_rows,
            )
        conn.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema_version", SCHEMA_VERSION),
                ("fts_enabled", "1" if fts_enabled else "0"),
                ("record_count", str(len(rows))),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def ensure_singapore_law_database_ready(
    *, force_rebuild: bool = False
) -> Dict[str, object]:
    """Create or reuse the independent Singapore-law SQLite database."""

    with _BUILD_LOCK:
        source = _source_manifest()
        cached = _read_cached_manifest()
        unchanged = (
            not force_rebuild
            and DB_PATH.exists()
            and cached is not None
            and cached.get("schema_version") == source["schema_version"]
            and cached.get("content_sha256") == source["content_sha256"]
        )
        if unchanged:
            return {
                "rebuilt": False,
                "mode": "unchanged",
                "content_sha256": source["content_sha256"],
                "db_path": str(DB_PATH),
                "schema_version": SCHEMA_VERSION,
                "record_count": source["record_count"],
            }

        records = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp_db = CACHE_DIR / "singapore_law.tmp.db"
        _build_database(records, temp_db)
        for suffix in ("", "-wal", "-shm"):
            current = Path(f"{DB_PATH}{suffix}")
            if current.exists():
                current.unlink()
        temp_db.replace(DB_PATH)
        manifest = {
            **source,
            "db_path": str(DB_PATH),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "rebuilt": True,
            "mode": "full",
            "content_sha256": source["content_sha256"],
            "db_path": str(DB_PATH),
            "schema_version": SCHEMA_VERSION,
            "record_count": source["record_count"],
        }


def _payload(row: sqlite3.Row) -> Dict[str, Any]:
    return json.loads(row["payload_json"])


def _section_refs(message: str) -> List[str]:
    refs = [match.group(1) for match in _EN_SECTION_RE.finditer(message)]
    refs.extend(match.group(1) for match in _ZH_SECTION_RE.finditer(message))
    seen = set()
    result = []
    for value in refs:
        normalized = _normalize_article_number(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _fts_query(query: str) -> str:
    tokens = [token for token in _normalize_text(query).split() if token]
    safe = [f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens[:12]]
    return " OR ".join(safe)


def _score(record: Dict[str, Any], query: str) -> float:
    normalized_query = _normalize_text(query)
    title = _normalize_text(record.get("law_name", ""))
    article = _normalize_article_number(record.get("article_number", ""))
    blob = _normalize_text(_search_blob(record))
    tokens = [token for token in normalized_query.split() if token]
    score = 0.0
    if normalized_query and normalized_query == title:
        score += 120.0
    elif normalized_query and normalized_query in title:
        score += 70.0
    if normalized_query and normalized_query in blob:
        score += 35.0
    if normalized_query and normalized_query == article:
        score += 25.0
    for token in tokens:
        if token in title:
            score += 14.0
        elif token in blob:
            score += 5.0
    return score


class SingaporeLawSearchEngine:
    def __init__(self) -> None:
        ensure_singapore_law_database_ready()

    @staticmethod
    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def exact_search(self, title: str, article_number: str) -> str:
        started = time.perf_counter()
        normalized_title = _normalize_text(title)
        normalized_article = _normalize_article_number(article_number)
        if not normalized_title or not normalized_article:
            return _json_dumps(
                {
                    "success": False,
                    "message": "title and article_number are required",
                    "data": None,
                    "search_time": round(time.perf_counter() - started, 6),
                }
            )
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM records
                WHERE normalized_law_name = ?
                  AND normalized_article_number = ?
                ORDER BY rule_id
                LIMIT 1
                """,
                (normalized_title, normalized_article),
            ).fetchone()
        return _json_dumps(
            {
                "success": row is not None,
                "message": "exact match" if row is not None else "no exact match",
                "data": _payload(row) if row is not None else None,
                "search_time": round(time.perf_counter() - started, 6),
            }
        )

    def _candidate_records(self, query: str) -> List[Dict[str, Any]]:
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return []
        found: Dict[str, Dict[str, Any]] = {}
        with self._connect() as conn:
            like = f"%{normalized_query}%"
            for row in conn.execute(
                """
                SELECT payload_json FROM records
                WHERE normalized_law_name LIKE ?
                   OR normalized_search_blob LIKE ?
                LIMIT 200
                """,
                (like, like),
            ):
                value = _payload(row)
                found[str(value["rule_id"])] = value

            fts = _fts_query(query)
            if fts:
                try:
                    rows = conn.execute(
                        """
                        SELECT r.payload_json
                        FROM records_fts
                        JOIN records AS r USING(rule_id)
                        WHERE records_fts MATCH ?
                        ORDER BY bm25(records_fts)
                        LIMIT 200
                        """,
                        (fts,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                for row in rows:
                    value = _payload(row)
                    found[str(value["rule_id"])] = value

            if not found:
                tokens = [token for token in normalized_query.split() if token][:8]
                if tokens:
                    clauses = " OR ".join("normalized_search_blob LIKE ?" for _ in tokens)
                    params = [f"%{token}%" for token in tokens]
                    for row in conn.execute(
                        f"SELECT payload_json FROM records WHERE {clauses} LIMIT 200",
                        params,
                    ):
                        value = _payload(row)
                        found[str(value["rule_id"])] = value
        return list(found.values())

    def fuzzy_search(self, query: str, limit: int = 5) -> str:
        started = time.perf_counter()
        limit = _clamp_limit(limit)
        if not str(query or "").strip():
            return _json_dumps(
                {
                    "success": False,
                    "message": "query is required",
                    "data": [],
                    "total_count": 0,
                    "returned_count": 0,
                    "search_time": round(time.perf_counter() - started, 6),
                }
            )
        candidates = self._candidate_records(query)
        ranked = sorted(
            candidates,
            key=lambda item: (-_score(item, query), str(item.get("rule_id", ""))),
        )
        data = ranked[:limit]
        return _json_dumps(
            {
                "success": bool(data),
                "message": "matches found" if data else "no match",
                "data": data,
                "total_count": len(ranked),
                "returned_count": len(data),
                "search_time": round(time.perf_counter() - started, 6),
            }
        )

    def link_search(self, message: str, limit: int = 5) -> str:
        started = time.perf_counter()
        limit = _clamp_limit(limit)
        text = str(message or "").strip()
        if not text:
            return _json_dumps(
                {
                    "success": False,
                    "message": "message is required",
                    "text": "",
                    "references": [],
                    "data": [],
                    "search_time": round(time.perf_counter() - started, 6),
                }
            )

        normalized_message = _normalize_text(text)
        requested_sections = _section_refs(text)
        direct: List[Dict[str, Any]] = []
        with self._connect() as conn:
            all_records = [_payload(row) for row in conn.execute("SELECT payload_json FROM records")]
        for record in all_records:
            title = _normalize_text(record.get("law_name", ""))
            citation = _normalize_text(record.get("citation", ""))
            direct_name = bool(title and title in normalized_message)
            direct_citation = bool(citation and citation in normalized_message)
            if not (direct_name or direct_citation):
                continue
            if requested_sections and _normalize_article_number(
                record.get("article_number", "")
            ) not in requested_sections:
                continue
            direct.append(record)

        if direct:
            ranked = sorted(
                direct,
                key=lambda item: (
                    _normalize_text(item.get("law_name", "")),
                    _normalize_article_number(item.get("article_number", "")),
                ),
            )[:limit]
        else:
            fuzzy = json.loads(self.fuzzy_search(text, limit=limit))
            ranked = list(fuzzy.get("data") or [])

        references = [
            {
                "title": item.get("law_name", ""),
                "article_number": item.get("article_number", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            }
            for item in ranked
        ]
        readable = []
        for index, item in enumerate(references, start=1):
            excerpt = _SPACE_RE.sub(" ", str(item["content"])).strip()
            if len(excerpt) > 500:
                excerpt = excerpt[:497].rstrip() + "..."
            readable.append(
                f"{index}. {item['title']} {item['article_number']}\n"
                f"{excerpt}\n{item['url']}"
            )
        return _json_dumps(
            {
                "success": bool(ranked),
                "message": "references resolved" if ranked else "no reference resolved",
                "text": "\n\n".join(readable),
                "references": references,
                "data": ranked,
                "search_time": round(time.perf_counter() - started, 6),
            }
        )


def get_engine() -> SingaporeLawSearchEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = SingaporeLawSearchEngine()
    return _ENGINE


def reset_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None


def exact_search(title: str, article_number: str) -> str:
    return get_engine().exact_search(title, article_number)


def fuzzy_search(query: str, limit: int = 5) -> str:
    return get_engine().fuzzy_search(query, limit)


def semantic_search(query: str, limit: int = 5) -> str:
    return fuzzy_search(query, limit)


def link_search(message: str, limit: int = 5) -> str:
    return get_engine().link_search(message, limit)


def singapore_law_exact_search(title: str, article_number: str) -> str:
    return exact_search(title, article_number)


def singapore_law_fuzzy_search(query: str, limit: int = 5) -> str:
    return fuzzy_search(query, limit)


def singapore_law_link_search(message: str, limit: int = 5) -> str:
    return link_search(message, limit)


if __name__ == "__main__":
    print(fuzzy_search("中央公积金 投资", limit=3))
