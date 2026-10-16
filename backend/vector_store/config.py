"""法律向量库、BM25、reranker 与混合检索配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BM25_PATH = REPO_ROOT / "data" / "vector_index" / "legal_bm25.sqlite3"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "data" / "vector_index" / "legal_index_manifest.json"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip()


@dataclass(frozen=True)
class LegalVectorConfig:
    vector_db_enabled: bool
    vector_retrieval_enabled: bool
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str
    vector_distance: str
    vector_search_limit: int
    vector_upsert_batch_size: int

    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_version: str
    embedding_timeout: float
    embedding_batch_size: int
    embedding_max_chars: int

    bm25_enabled: bool
    bm25_top_k: int
    bm25_path: Path
    hybrid_top_k: int
    rrf_k: int
    final_retrieval_k: int

    reranker_enabled: bool
    reranker_base_url: str
    reranker_api_key: str
    reranker_model: str
    reranker_top_k: int
    reranker_final_k: int
    reranker_timeout: float

    index_version: str
    data_version: str
    chunking_version: str
    manifest_path: Path
    max_chunk_chars: int

    def embedding_ready(self) -> bool:
        return bool(self.embedding_base_url and self.embedding_api_key and self.embedding_model)

    def collection_name(self) -> str:
        if self.qdrant_collection:
            return self.qdrant_collection
        version = self.embedding_version or "default"
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in version)
        return f"lawver_public_law_{safe}"


@lru_cache(maxsize=1)
def get_legal_vector_config() -> LegalVectorConfig:
    embedding_base = _env_str("LAWVER_LEGAL_EMBEDDING_BASE_URL") or _env_str("EMBEDDING_BASE_URL")
    embedding_key = _env_str("LAWVER_LEGAL_EMBEDDING_API_KEY") or _env_str("EMBEDDING_API_KEY")
    embedding_model = _env_str("LAWVER_LEGAL_EMBEDDING_MODEL") or _env_str("EMBEDDING_MODEL")
    embedding_version = _env_str("LAWVER_LEGAL_EMBEDDING_VERSION") or (
        embedding_model.replace("/", "-").lower() + "-v1" if embedding_model else ""
    )
    bm25_path = Path(_env_str("LAWVER_BM25_PATH") or str(DEFAULT_BM25_PATH))
    manifest_path = Path(_env_str("LAWVER_LEGAL_MANIFEST_PATH") or str(DEFAULT_MANIFEST_PATH))
    return LegalVectorConfig(
        vector_db_enabled=_env_bool("LAWVER_VECTOR_DB_ENABLED", False),
        vector_retrieval_enabled=_env_bool("LAWVER_VECTOR_RETRIEVAL_ENABLED", False),
        qdrant_url=_env_str("LAWVER_QDRANT_URL", "http://127.0.0.1:6333"),
        qdrant_api_key=_env_str("LAWVER_QDRANT_API_KEY"),
        qdrant_collection=_env_str("LAWVER_QDRANT_COLLECTION"),
        vector_distance=_env_str("LAWVER_VECTOR_DISTANCE", "Cosine") or "Cosine",
        vector_search_limit=_env_int("LAWVER_VECTOR_SEARCH_LIMIT", 50),
        vector_upsert_batch_size=_env_int("LAWVER_VECTOR_UPSERT_BATCH_SIZE", 64),
        embedding_base_url=embedding_base.rstrip("/"),
        embedding_api_key=embedding_key,
        embedding_model=embedding_model,
        embedding_version=embedding_version,
        embedding_timeout=_env_float("LAWVER_LEGAL_EMBEDDING_TIMEOUT", 8.0),
        embedding_batch_size=_env_int("LAWVER_LEGAL_EMBEDDING_BATCH_SIZE", 32),
        embedding_max_chars=_env_int("LAWVER_LEGAL_EMBEDDING_MAX_CHARS", 1800),
        bm25_enabled=_env_bool("LAWVER_BM25_ENABLED", True),
        bm25_top_k=_env_int("LAWVER_BM25_TOP_K", 50),
        bm25_path=bm25_path,
        hybrid_top_k=_env_int("LAWVER_HYBRID_TOP_K", 20),
        rrf_k=_env_int("LAWVER_RRF_K", 60),
        final_retrieval_k=_env_int("LAWVER_FINAL_RETRIEVAL_K", 8),
        reranker_enabled=_env_bool("LAWVER_RERANKER_ENABLED", False),
        reranker_base_url=(
            _env_str("LAWVER_RERANKER_BASE_URL")
            or embedding_base
        ).rstrip("/"),
        reranker_api_key=_env_str("LAWVER_RERANKER_API_KEY") or embedding_key,
        reranker_model=_env_str("LAWVER_RERANKER_MODEL"),
        reranker_top_k=_env_int("LAWVER_RERANKER_TOP_K", 20),
        reranker_final_k=_env_int("LAWVER_RERANKER_FINAL_K", 8),
        reranker_timeout=_env_float("LAWVER_RERANKER_TIMEOUT", 3.0),
        index_version=_env_str("LAWVER_LEGAL_INDEX_VERSION", "article-v1") or "article-v1",
        data_version=_env_str("LAWVER_LEGAL_DATA_VERSION"),
        chunking_version=_env_str("LAWVER_LEGAL_CHUNKING_VERSION", "article-v1") or "article-v1",
        manifest_path=manifest_path,
        max_chunk_chars=_env_int("LAWVER_LEGAL_MAX_CHUNK_CHARS", 1800),
    )


def clear_config_cache() -> None:
    get_legal_vector_config.cache_clear()
