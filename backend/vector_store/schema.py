"""法律 chunk / payload 数据结构与稳定 point_id。"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


CN_NUM = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
CN_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10000}
ARTICLE_TOKEN = r"[一二三四五六七八九十百千万零〇两0-9]+"
ARTICLE_NUMBER_RE = re.compile(
    rf"第(?P<main>{ARTICLE_TOKEN})条(?:之(?P<sub>{ARTICLE_TOKEN}))?"
)
REVISION_RE = re.compile(r"(20\d{2})\s*(修订|修正|修改)")
NOT_YET_RE = re.compile(r"尚未施行|未施行")
REPEALED_KEYWORDS = ("废止", "失效", "已被修改", "repealed", "revoked")


def chinese_to_int(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in CN_NUM:
            number = CN_NUM[char]
        elif char in CN_UNIT:
            section += (number or 1) * CN_UNIT[char]
            number = 0
        else:
            return None
    return total + section + number


def normalize_article_number(article_number: str) -> str:
    text = (article_number or "").replace(" ", "").strip()
    match = ARTICLE_NUMBER_RE.search(text)
    if match:
        main = chinese_to_int(match.group("main"))
        sub = chinese_to_int(match.group("sub")) if match.group("sub") else None
        if main is None:
            return ""
        return f"{main}-{sub}" if sub is not None else str(main)
    # 东盟等非「第N条」写法：提取首个数字段
    digits = re.search(r"(\d+)\s*([a-zA-Z])?", text)
    if digits:
        suffix = (digits.group(2) or "").lower()
        return f"{digits.group(1)}{suffix}"
    return text.casefold()[:40]


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def make_point_id(
    *,
    source_id: str,
    article_number: str,
    revision_label: str,
    chunk_index: int,
    content_hash_value: str,
) -> str:
    raw = "|".join(
        [
            str(source_id or ""),
            str(article_number or ""),
            str(revision_label or ""),
            str(int(chunk_index)),
            str(content_hash_value or ""),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return str(uuid.UUID(hex=digest[:32]))


def map_effective_status(effectiveness: str | None, status: str | None = None) -> str:
    text = f"{effectiveness or ''} {status or ''}".strip().casefold()
    if not text:
        return "in_force"
    if any(keyword.casefold() in text for keyword in REPEALED_KEYWORDS):
        return "repealed"
    if NOT_YET_RE.search(text) or "not yet" in text:
        return "not_yet_in_force"
    if "现行有效" in (effectiveness or "") or "in force" in text or "有效" in (effectiveness or ""):
        return "in_force"
    return "in_force"


def extract_revision_label(law_name: str, effectiveness: str = "") -> str:
    for source in (law_name, effectiveness):
        match = REVISION_RE.search(source or "")
        if match:
            return f"{match.group(1)}{match.group(2)}"
    if NOT_YET_RE.search(law_name or "") or NOT_YET_RE.search(effectiveness or ""):
        return "尚未施行"
    return ""


def clean_law_name(law_name: str) -> str:
    text = (law_name or "").strip()
    text = text.replace("《", "").replace("》", "")
    text = re.sub(r"\s+English\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def build_embedding_text(
    *,
    law_name: str,
    article_number: str,
    jurisdiction: str,
    content: str,
) -> str:
    return (
        f"法律名称：《{clean_law_name(law_name)}》\n"
        f"条号：{article_number}\n"
        f"法域：{jurisdiction}\n"
        f"正文：{content}"
    )


@dataclass
class LawChunk:
    text: str
    law_name: str
    short_name: str
    article_number: str
    article_number_normalized: str
    article_id: str
    source_id: str
    source_file: str
    content_hash: str
    law_type: str
    jurisdiction: str
    legal_system: str
    effective_status: str
    effective_date: str = ""
    repeal_date: str | None = None
    revision_label: str = ""
    source_url: str = ""
    chunk_index: int = 0
    chunk_count: int = 1
    embedding_model: str = ""
    embedding_version: str = ""
    chunking_version: str = "article-v1"
    reranker_model: str = ""
    indexed_at: str = ""
    point_id: str = ""
    embedding_text: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    routes: list[str] = field(default_factory=list)

    def ensure_ids(self) -> None:
        if not self.content_hash:
            self.content_hash = content_hash(self.text)
        if not self.point_id:
            self.point_id = make_point_id(
                source_id=self.source_id,
                article_number=self.article_number,
                revision_label=self.revision_label,
                chunk_index=self.chunk_index,
                content_hash_value=self.content_hash,
            )
        if not self.article_id:
            short = self.short_name or clean_law_name(self.law_name)
            self.article_id = f"{short}:{self.article_number_normalized or self.article_number}"
        if not self.embedding_text:
            self.embedding_text = build_embedding_text(
                law_name=self.law_name,
                article_number=self.article_number,
                jurisdiction=self.jurisdiction,
                content=self.text,
            )
        if not self.indexed_at:
            self.indexed_at = datetime.now(timezone.utc).isoformat()

    def to_payload(self) -> dict[str, Any]:
        self.ensure_ids()
        payload = asdict(self)
        payload.pop("scores", None)
        payload.pop("routes", None)
        payload.pop("embedding_text", None)
        payload.pop("point_id", None)
        return payload

    def dedupe_key(self) -> tuple[str, str, str, str]:
        return (
            self.jurisdiction or "",
            self.source_id or "",
            self.article_number_normalized or self.article_number or "",
            self.revision_label or "",
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, point_id: str = "") -> "LawChunk":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {key: value for key, value in payload.items() if key in known}
        chunk = cls(**data)  # type: ignore[arg-type]
        if point_id:
            chunk.point_id = point_id
        chunk.ensure_ids()
        return chunk


PAYLOAD_INDEX_FIELDS = (
    "jurisdiction",
    "legal_system",
    "law_type",
    "law_name",
    "article_number_normalized",
    "effective_status",
    "source_id",
    "content_hash",
)
