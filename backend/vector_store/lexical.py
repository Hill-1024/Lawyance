"""BM25 词法检索：jieba + 字符 bigram，SQLite sidecar 存文档。"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .config import LegalVectorConfig, get_legal_vector_config
from .schema import LawChunk

logger = logging.getLogger(__name__)

try:
    import jieba
except ImportError:  # pragma: no cover
    jieba = None  # type: ignore[assignment]

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover
    BM25Okapi = None  # type: ignore[misc,assignment]


class _FallbackBM25:
    """rank-bm25 缺失时的纯 Python Okapi 实现，避免检索链整体不可用。"""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        import math
        from collections import Counter

        self._k1 = k1
        self._b = b
        self._docs = [Counter(doc) for doc in corpus]
        self._lengths = [float(len(doc)) for doc in corpus]
        self._avgdl = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        df: dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        n = len(corpus)
        self._idf = {
            term: math.log(1.0 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def get_scores(self, query: list[str]) -> list[float]:
        scores: list[float] = []
        for doc, length in zip(self._docs, self._lengths):
            total = 0.0
            norm = 1.0 - self._b + self._b * (length / self._avgdl) if self._avgdl else 1.0
            for term in query:
                freq = doc.get(term, 0)
                if not freq:
                    continue
                idf = self._idf.get(term, 0.0)
                total += idf * (freq * (self._k1 + 1.0)) / (freq + self._k1 * norm)
            scores.append(total)
        return scores

_LOCK = threading.Lock()
_ENGINE: "LexicalRetriever | None" = None
_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    raw = str(text or "").strip().casefold()
    if not raw:
        return []
    tokens: list[str] = []
    if jieba is not None:
        tokens.extend(tok.strip() for tok in jieba.cut_for_search(raw) if tok.strip())
    else:
        tokens.extend(_TOKEN_RE.findall(raw))
    # 字符 bigram：保留法律固定表达
    compact = re.sub(r"\s+", "", raw)
    for index in range(len(compact) - 1):
        pair = compact[index : index + 2]
        if _TOKEN_RE.fullmatch(pair) or all("\u4e00" <= ch <= "\u9fff" for ch in pair):
            tokens.append(pair)
    # 去重保序
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token in seen or len(token) < 1:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


class LexicalRetriever:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._bm25: Any | None = None
        self._doc_ids: list[str] = []
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    point_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    law_name TEXT NOT NULL,
                    article_number TEXT NOT NULL,
                    article_number_normalized TEXT NOT NULL,
                    jurisdiction TEXT NOT NULL,
                    legal_system TEXT NOT NULL,
                    effective_status TEXT NOT NULL,
                    revision_label TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    tokens_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_lex_jurisdiction ON documents(jurisdiction);
                CREATE INDEX IF NOT EXISTS idx_lex_system ON documents(legal_system);
                CREATE INDEX IF NOT EXISTS idx_lex_status ON documents(effective_status);
                CREATE INDEX IF NOT EXISTS idx_lex_law ON documents(law_name);
                CREATE INDEX IF NOT EXISTS idx_lex_article ON documents(article_number_normalized);
                CREATE INDEX IF NOT EXISTS idx_lex_source ON documents(source_id);
                """
            )
            conn.commit()

    def clear(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM documents")
            conn.commit()
        self._bm25 = None
        self._doc_ids = []

    def delete_by_source_ids(self, source_ids: Iterable[str]) -> None:
        ids = [str(item) for item in source_ids if item]
        if not ids:
            return
        with closing(self._connect()) as conn:
            conn.executemany("DELETE FROM documents WHERE source_id = ?", [(item,) for item in ids])
            conn.commit()
        self._bm25 = None

    def index(self, documents: Iterable[LawChunk], *, replace: bool = False) -> int:
        chunks = list(documents)
        if replace:
            self.clear()
        rows = []
        for chunk in chunks:
            chunk.ensure_ids()
            search_text = " ".join(
                [
                    chunk.law_name,
                    chunk.short_name,
                    chunk.article_number,
                    chunk.article_number_normalized,
                    chunk.text,
                ]
            )
            tokens = tokenize(search_text)
            rows.append(
                (
                    chunk.point_id,
                    chunk.source_id,
                    chunk.law_name,
                    chunk.article_number,
                    chunk.article_number_normalized,
                    chunk.jurisdiction,
                    chunk.legal_system,
                    chunk.effective_status,
                    chunk.revision_label,
                    json.dumps(chunk.to_payload(), ensure_ascii=False),
                    search_text,
                    json.dumps(tokens, ensure_ascii=False),
                )
            )
        with closing(self._connect()) as conn:
            conn.executemany(
                """
                INSERT INTO documents(
                    point_id, source_id, law_name, article_number, article_number_normalized,
                    jurisdiction, legal_system, effective_status, revision_label,
                    payload_json, search_text, tokens_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(point_id) DO UPDATE SET
                    source_id=excluded.source_id,
                    law_name=excluded.law_name,
                    article_number=excluded.article_number,
                    article_number_normalized=excluded.article_number_normalized,
                    jurisdiction=excluded.jurisdiction,
                    legal_system=excluded.legal_system,
                    effective_status=excluded.effective_status,
                    revision_label=excluded.revision_label,
                    payload_json=excluded.payload_json,
                    search_text=excluded.search_text,
                    tokens_json=excluded.tokens_json
                """,
                rows,
            )
            conn.commit()
        self._bm25 = None
        return len(rows)

    def _load_bm25(self) -> tuple[Any, list[str], list[sqlite3.Row]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM documents").fetchall()
        corpus = [json.loads(row["tokens_json"]) for row in rows]
        doc_ids = [row["point_id"] for row in rows]
        if not corpus:
            self._bm25 = None
            self._doc_ids = doc_ids
            return None, doc_ids, rows
        engine = BM25Okapi(corpus) if BM25Okapi is not None else _FallbackBM25(corpus)
        self._bm25 = engine
        self._doc_ids = doc_ids
        return engine, doc_ids, rows

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> list[LawChunk]:
        filters = filters or {}
        jurisdictions = set(filters.get("jurisdictions") or [])
        legal_systems = set(filters.get("legal_systems") or [])
        statuses = set(filters.get("effective_statuses") or ["in_force"])
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        bm25, _doc_ids, rows = self._load_bm25()
        if not rows or bm25 is None:
            return []

        scores = bm25.get_scores(query_tokens)
        ranked: list[tuple[float, int, sqlite3.Row]] = []
        for index, row in enumerate(rows):
            if jurisdictions and row["jurisdiction"] not in jurisdictions:
                continue
            if legal_systems and row["legal_system"] not in legal_systems:
                continue
            if statuses and row["effective_status"] not in statuses:
                continue
            # rank-bm25 在小语料上 IDF 可为负；用词重叠判断相关性，勿用 score>0 硬过滤
            doc_tokens = set(json.loads(row["tokens_json"]) or [])
            overlap = sum(1 for token in query_tokens if token in doc_tokens)
            score = float(scores[index])
            # 结构化字段加分：法名 / 条号字面命中
            lowered = query.casefold()
            structural = 0.0
            if row["law_name"] and row["law_name"].casefold() in lowered:
                structural += 8.0
            if row["article_number"] and row["article_number"] in query:
                structural += 6.0
            if row["article_number_normalized"] and row["article_number_normalized"] in query:
                structural += 4.0
            score += structural
            if overlap <= 0 and structural <= 0:
                continue
            ranked.append((score, index, row))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        hits: list[LawChunk] = []
        for rank, (score, _index, row) in enumerate(ranked[: max(1, limit)], start=1):
            payload = json.loads(row["payload_json"])
            chunk = LawChunk.from_payload(payload, point_id=row["point_id"])
            chunk.scores["lexical"] = score
            chunk.scores["lexical_rank"] = float(rank)
            tokens = set(json.loads(row["tokens_json"]))
            matched = [token for token in query_tokens if token in tokens][:20]
            chunk.scores["matched_term_count"] = float(len(matched))
            chunk.routes.append("bm25")
            # 调试字段放进 scores 以外的轻量元数据通过 routes 已够；matched_terms 写到 text 旁不合适
            hits.append(chunk)
        return hits

    def count(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()
        return int(row["c"] if row else 0)


def get_lexical_retriever(config: LegalVectorConfig | None = None) -> LexicalRetriever:
    global _ENGINE
    cfg = config or get_legal_vector_config()
    with _LOCK:
        if _ENGINE is None or Path(_ENGINE.path) != Path(cfg.bm25_path):
            _ENGINE = LexicalRetriever(cfg.bm25_path)
        return _ENGINE


def reset_lexical_retriever() -> None:
    global _ENGINE
    with _LOCK:
        _ENGINE = None
