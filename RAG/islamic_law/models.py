"""
模块描述：伊斯兰法系双层模型 dataclass。
- ShariaPrinciple：宗教法源共享层
- IslamicRule：国家转化实例层
- TermEntry：四语术语
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Iterable


ALLOWED_STATUS = frozenset({"in_force", "repealed", "amended", "unknown"})
ALLOWED_LEGAL_EFFECT = frozenset(
    {"binding", "regulated-fatwa", "religious-guidance", "advisory", ""}
)
# advisory 兼容旧写法，入库时归一为 religious-guidance
LEGAL_EFFECT_ALIASES = {"advisory": "religious-guidance"}

ALLOWED_SHARIA_SOURCE = frozenset(
    {
        "Quran",
        "Hadith",
        "Ijma",
        "Qiyas",
        "Fatwa",
        "Statute",
        "Qanun",
        "CourtRuling",
        "Standard",
        "",
    }
)

_ARTICLE_HINT_RE = re.compile(
    r"(?:Section|Article|Art\.?|Seksyen|Pasal|المادة)\s*([0-9]+(?:\s*[A-Za-z])?)",
    re.IGNORECASE,
)


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_law_name_key(text: str) -> str:
    text = _norm_ws(text).lower()
    text = text.replace("《", "").replace("》", "")
    return re.sub(r"[\s\-—_·•:：,，.。/\\()'\"“”‘’]+", "", text)


def normalize_article_key(article_number: str) -> str:
    text = _norm_ws(article_number)
    match = _ARTICLE_HINT_RE.search(text)
    if match:
        return re.sub(r"\s+", "", match.group(1)).upper()
    digits = re.findall(r"[0-9]+[A-Za-z]?", text)
    if digits:
        return digits[0].upper()
    return normalize_law_name_key(text)


def normalize_legal_effect(value: str) -> str:
    text = _norm_ws(value).lower()
    head = text.split("（", 1)[0].split("(", 1)[0].strip()
    head = LEGAL_EFFECT_ALIASES.get(head, head)
    if head in ALLOWED_LEGAL_EFFECT:
        return head
    return text


def _parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except json.JSONDecodeError:
        pass
    return [x.strip() for x in raw.split(",") if x.strip()]


def _row_to_dataclass(cls: type, row: Any):
    data = dict(row)
    allowed = {f.name for f in fields(cls)}
    if "country_rule_ids" in allowed and "country_rule_ids" in data:
        data["country_rule_ids"] = _parse_json_list(data.get("country_rule_ids"))
    if "aliases_json" in allowed and "aliases" not in data:
        # TermEntry uses aliases list in Python, aliases_json in DB
        pass
    filtered = {k: v for k, v in data.items() if k in allowed}
    return cls(**filtered)


@dataclass
class ShariaPrinciple:
    """宗教法源共享层：跨国唯一原则记录。"""

    sharia_principle_id: str
    rule_subject: str
    content: str = ""
    madhhab: str = "Shafi'i"
    sharia_source_type: str = ""
    religious_anchor: str = ""
    arabic_text: str = ""
    transliteration: str = ""
    legal_effect: str = "religious-guidance"
    parallel_languages: str = ""
    url: str = ""
    country_rule_ids: list[str] = field(default_factory=list)
    search_blob: str = ""

    def __post_init__(self) -> None:
        self.sharia_principle_id = _norm_ws(self.sharia_principle_id)
        self.rule_subject = _norm_ws(self.rule_subject)
        self.content = str(self.content or "").strip()
        self.madhhab = _norm_ws(self.madhhab) or "Shafi'i"
        self.sharia_source_type = _norm_ws(self.sharia_source_type)
        self.legal_effect = normalize_legal_effect(self.legal_effect) or "religious-guidance"
        self.country_rule_ids = _parse_json_list(self.country_rule_ids)
        if not self.search_blob:
            self.search_blob = self.build_search_blob()
        if not self.sharia_principle_id or not self.rule_subject:
            raise ValueError("sharia_principle_id / rule_subject are required")

    def build_search_blob(self) -> str:
        parts = [
            self.sharia_principle_id,
            self.rule_subject,
            self.content,
            self.madhhab,
            self.sharia_source_type,
            self.religious_anchor,
            self.arabic_text,
            self.transliteration,
            " ".join(self.country_rule_ids),
        ]
        return "\n".join(p for p in parts if p)

    def to_db_params(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["country_rule_ids"] = json.dumps(self.country_rule_ids, ensure_ascii=False)
        payload["search_blob"] = self.search_blob or self.build_search_blob()
        return payload

    @classmethod
    def from_row(cls, row: Any) -> "ShariaPrinciple":
        return _row_to_dataclass(cls, row)

    def to_summary(self) -> dict[str, Any]:
        return {
            "sharia_principle_id": self.sharia_principle_id,
            "rule_subject": self.rule_subject,
            "madhhab": self.madhhab,
            "sharia_source_type": self.sharia_source_type,
            "religious_anchor": self.religious_anchor,
            "legal_effect": self.legal_effect,
            "content": self.content,
            "url": self.url,
            "country_rule_ids": list(self.country_rule_ids),
        }


@dataclass
class IslamicRule:
    """国家转化实例层：挂接各国的立法/监管/法特瓦转化。"""

    rule_id: str
    law_name: str
    content: str
    country: str
    article_number: str = ""
    url: str = ""
    source_id: str = ""
    status: str = "unknown"
    effective_date: str = ""
    language: str = "en"
    country_label: str = ""

    rule_subject: str = ""
    national_transformation: str = ""
    parallel_languages: str = ""
    output_annotation: str = ""

    madhhab: str = ""
    sharia_source_type: str = ""
    religious_anchor: str = ""
    fatwa_issuer: str = ""
    fatwa_id: str = ""
    supersedes: str = ""
    legal_effect: str = ""
    applicability_person: str = ""
    applicability_subject: str = ""
    applicability_territory: str = ""
    arabic_text: str = ""
    transliteration: str = ""
    sharia_principle_id: str = ""
    country_rule_ids: list[str] = field(default_factory=list)

    law_name_key: str = ""
    article_key: str = ""
    search_blob: str = ""

    def __post_init__(self) -> None:
        self.rule_id = _norm_ws(self.rule_id)
        self.law_name = _norm_ws(self.law_name)
        self.content = str(self.content or "").strip()
        self.country = _norm_ws(self.country).upper()
        self.article_number = _norm_ws(self.article_number)
        self.status = (_norm_ws(self.status) or "unknown").lower()
        if self.status not in ALLOWED_STATUS:
            self.status = "unknown"
        self.language = _norm_ws(self.language).lower() or "en"
        self.sharia_source_type = _norm_ws(self.sharia_source_type)
        self.sharia_principle_id = _norm_ws(self.sharia_principle_id)
        self.legal_effect = normalize_legal_effect(self.legal_effect)
        self.country_rule_ids = _parse_json_list(self.country_rule_ids)

        if not self.source_id:
            self.source_id = self.rule_id
        if not self.law_name_key:
            self.law_name_key = normalize_law_name_key(self.law_name)
        if not self.article_key:
            self.article_key = normalize_article_key(self.article_number)
        if not self.search_blob:
            self.search_blob = self.build_search_blob()

        if not self.rule_id or not self.law_name or not self.content or not self.country:
            raise ValueError("rule_id / law_name / content / country are required")

    def build_search_blob(self) -> str:
        parts = [
            self.rule_id,
            self.rule_subject,
            self.law_name,
            self.article_number,
            self.content,
            self.national_transformation,
            self.religious_anchor,
            self.madhhab,
            self.sharia_source_type,
            self.fatwa_issuer,
            self.fatwa_id,
            self.applicability_person,
            self.applicability_subject,
            self.applicability_territory,
            self.arabic_text,
            self.transliteration,
            self.sharia_principle_id,
            self.country,
            self.country_label,
            " ".join(self.country_rule_ids),
        ]
        return "\n".join(p for p in parts if p)

    def to_db_params(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["country_rule_ids"] = json.dumps(self.country_rule_ids, ensure_ascii=False)
        payload["search_blob"] = self.search_blob or self.build_search_blob()
        if not payload.get("sharia_principle_id"):
            payload["sharia_principle_id"] = None
        return payload

    @classmethod
    def from_row(cls, row: Any) -> "IslamicRule":
        data = dict(row)
        # 兼容旧列名
        if "sharia_principle_id" not in data and data.get("linked_principle_id"):
            data["sharia_principle_id"] = data["linked_principle_id"]
        return _row_to_dataclass(cls, data)

    def to_canonical_result(self, principle: ShariaPrinciple | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "law_name": self.law_name,
            "article_number": self.article_number,
            "content": self.content,
            "url": self.url,
            "source_id": self.source_id or self.rule_id,
            "status": self.status,
            "effective_date": self.effective_date,
            "language": self.language,
            "country": self.country,
            "country_label": self.country_label,
            "jurisdiction": self.country_label or self.country,
            "legal_system": "islamic",
            "rule_id": self.rule_id,
            "rule_subject": self.rule_subject,
            "madhhab": self.madhhab,
            "legal_effect": self.legal_effect,
            "applicability_person": self.applicability_person,
            "applicability_subject": self.applicability_subject,
            "applicability_territory": self.applicability_territory,
            "sharia_principle_id": self.sharia_principle_id,
            "fatwa_issuer": self.fatwa_issuer,
            "fatwa_id": self.fatwa_id,
            "national_transformation": self.national_transformation,
            "output_annotation": self.output_annotation,
        }
        if principle is not None:
            result["principle"] = principle.to_summary()
        return result


@dataclass
class TermEntry:
    """四语术语对照表条目。"""

    term_id: str
    en: str = ""
    zh: str = ""
    preferred_zh: str = ""
    ar: str = ""
    ms: str = ""
    id: str = ""
    aliases: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.term_id = _norm_ws(self.term_id)
        self.en = _norm_ws(self.en)
        self.zh = _norm_ws(self.zh)
        self.preferred_zh = _norm_ws(self.preferred_zh) or self.zh
        self.aliases = _parse_json_list(self.aliases)
        if not self.term_id:
            raise ValueError("term_id is required")

    def to_db_params(self) -> dict[str, Any]:
        return {
            "term_id": self.term_id,
            "ar": self.ar,
            "en": self.en,
            "zh": self.zh,
            "ms": self.ms,
            "id": self.id,
            "preferred_zh": self.preferred_zh,
            "aliases_json": json.dumps(self.aliases, ensure_ascii=False),
            "notes": self.notes,
        }


INSERT_PRINCIPLE_SQL = """
INSERT OR REPLACE INTO sharia_principles (
    sharia_principle_id, rule_subject, madhhab, sharia_source_type, religious_anchor,
    arabic_text, transliteration, content, legal_effect, parallel_languages, url,
    country_rule_ids, search_blob, updated_at
) VALUES (
    :sharia_principle_id, :rule_subject, :madhhab, :sharia_source_type, :religious_anchor,
    :arabic_text, :transliteration, :content, :legal_effect, :parallel_languages, :url,
    :country_rule_ids, :search_blob, datetime('now')
)
"""

INSERT_RULE_SQL = """
INSERT OR REPLACE INTO islamic_rules (
    rule_id, source_id, law_name, article_number, content, url,
    status, effective_date, language, country, country_label,
    rule_subject, national_transformation, parallel_languages, output_annotation,
    madhhab, sharia_source_type, religious_anchor, fatwa_issuer, fatwa_id, supersedes,
    legal_effect, applicability_person, applicability_subject, applicability_territory,
    arabic_text, transliteration, sharia_principle_id, country_rule_ids,
    law_name_key, article_key, search_blob, updated_at
) VALUES (
    :rule_id, :source_id, :law_name, :article_number, :content, :url,
    :status, :effective_date, :language, :country, :country_label,
    :rule_subject, :national_transformation, :parallel_languages, :output_annotation,
    :madhhab, :sharia_source_type, :religious_anchor, :fatwa_issuer, :fatwa_id, :supersedes,
    :legal_effect, :applicability_person, :applicability_subject, :applicability_territory,
    :arabic_text, :transliteration, :sharia_principle_id, :country_rule_ids,
    :law_name_key, :article_key, :search_blob, datetime('now')
)
"""

INSERT_TERM_SQL = """
INSERT OR REPLACE INTO terminology (
    term_id, ar, en, zh, ms, id, preferred_zh, aliases_json, notes
) VALUES (
    :term_id, :ar, :en, :zh, :ms, :id, :preferred_zh, :aliases_json, :notes
)
"""

INSERT_AUTHORITY_SQL = """
INSERT OR REPLACE INTO authority_sources (
    source_key, country, layer, organization, channels, primary_use, homepage_url, notes
) VALUES (
    :source_key, :country, :layer, :organization, :channels, :primary_use, :homepage_url, :notes
)
"""


def insert_principles(conn: Any, items: Iterable[ShariaPrinciple]) -> int:
    count = 0
    for item in items:
        conn.execute(INSERT_PRINCIPLE_SQL, item.to_db_params())
        count += 1
    return count


def insert_rules(conn: Any, rules: Iterable[IslamicRule]) -> int:
    count = 0
    for rule in rules:
        conn.execute(INSERT_RULE_SQL, rule.to_db_params())
        count += 1
    return count


def insert_terms(conn: Any, terms: Iterable[TermEntry]) -> int:
    count = 0
    for term in terms:
        conn.execute(INSERT_TERM_SQL, term.to_db_params())
        count += 1
    return count
