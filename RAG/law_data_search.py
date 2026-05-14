"""
模块描述：本地法律法规检索引擎，负责从 RAG/data 构建索引并提供精确、模糊和关联检索。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

BASE_DIR = Path(__file__).resolve().parent
RAW_DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
DB_PATH = CACHE_DIR / "law.db"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
SCHEMA_VERSION = 3
MAX_TITLE_CHARS = 160
MAX_ARTICLE_NUMBER_CHARS = 40
MAX_QUERY_CHARS = 4000
MAX_SEARCH_LIMIT = 20
MAX_QUERY_TERMS = 32
MIN_PARTIAL_TITLE_CHARS = 2

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
ARTICLE_HEADER_RE = re.compile(
    rf"(?m)^[ \t\u3000]*(?P<number>第{ARTICLE_TOKEN}条(?:之{ARTICLE_TOKEN})?)[ \t\u3000]*"
)
QUOTED_CITATION_RE = re.compile(
    rf"《(?P<title>[^》\n]{{2,80}})》(?P<number>第{ARTICLE_TOKEN}条(?:之{ARTICLE_TOKEN})?)"
)
TITLE_SUFFIX_RE = re.compile(r"\s*(English)?(已被修改|废止或失效)?\s*$")
FILE_TITLE_PAREN_RE = re.compile(r"[（(][^)）]+[)）]\s*$")
SKIP_EFFECTIVENESS_KEYWORDS = ("废止", "失效", "已被修改")
QUERY_SYNONYMS = {
    "醉驾": ["醉酒驾驶", "危险驾驶罪"],
    "酒驾": ["饮酒驾驶", "醉酒驾驶"],
    "危险驾驶罪": ["危险驾驶", "危险驾驶罪"],
    "违约金": ["违约责任", "违约金"],
    "工伤": ["工伤保险", "工伤认定"],
}

BUILD_LOCK = threading.Lock()


@dataclass
class Article:
    law_name: str
    article_number: str
    content: str
    category: str = ""
    url: str = ""
    cli: str = ""


@dataclass
class SourceLaw:
    law_name: str
    short_name: str
    metadata: Dict[str, str]
    articles: List[Tuple[str, str]]
    category: str


class LawSearchEngine:
    """基于 SQLite 的本地法律检索引擎。"""

    def __init__(self) -> None:
        if not RAW_DATA_DIR.exists():
            raise ValueError(f"法律语料目录不存在: {RAW_DATA_DIR}")
        self._ensure_built()

    def exact_search(self, law_name: str, article_number: str) -> str:
        start_time = time.time()
        result = {
            "success": False,
            "message": "",
            "data": None,
            "search_time": 0.0,
        }

        law_name = trim_text(law_name, MAX_TITLE_CHARS)
        article_number = trim_text(article_number, MAX_ARTICLE_NUMBER_CHARS)
        if not law_name or not article_number:
            result["message"] = "法律名称和条号不能为空"
            result["search_time"] = time.time() - start_time
            return json.dumps(result, ensure_ascii=False)

        law = self._find_law_by_name(law_name)
        if not law:
            result["message"] = f"未找到法律: {law_name}"
            result["search_time"] = time.time() - start_time
            return json.dumps(result, ensure_ascii=False)

        normalized_article = normalize_article_number(article_number)
        if not normalized_article:
            result["message"] = f"无法识别法条号: {article_number}"
            result["search_time"] = time.time() - start_time
            return json.dumps(result, ensure_ascii=False)

        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT laws.law_name, laws.category, laws.url, laws.cli,
                       articles.article_number, articles.content
                FROM articles
                JOIN laws ON laws.id = articles.law_id
                WHERE laws.id = ? AND articles.normalized_article = ?
                LIMIT 1
                """,
                (law["id"], normalized_article),
            ).fetchone()

        if not row:
            result["message"] = f"未找到法条: {law['law_name']} {article_number}"
            result["search_time"] = time.time() - start_time
            return json.dumps(result, ensure_ascii=False)

        result["success"] = True
        result["message"] = "找到匹配的法条"
        result["data"] = asdict(
            Article(
                law_name=row["law_name"],
                article_number=row["article_number"],
                content=row["content"],
                category=row["category"],
                url=row["url"],
                cli=row["cli"],
            )
        )
        result["search_time"] = time.time() - start_time
        return json.dumps(result, ensure_ascii=False)

    def fuzzy_search(self, keyword: str, limit: int = 5) -> str:
        start_time = time.time()
        safe_limit = normalize_limit(limit)
        result = {
            "success": False,
            "message": "",
            "data": [],
            "total_count": 0,
            "returned_count": 0,
            "search_time": 0.0,
        }

        query = normalize_query(trim_text(keyword, MAX_QUERY_CHARS))
        if not query:
            result["message"] = "检索关键词不能为空"
            result["search_time"] = time.time() - start_time
            return json.dumps(result, ensure_ascii=False)

        terms = build_query_terms(query)
        candidates: List[Tuple[int, Dict[str, str]]] = []

        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                SELECT laws.law_name, laws.category, laws.url, laws.cli,
                       articles.article_number, articles.content, articles.search_blob
                FROM articles
                JOIN laws ON laws.id = articles.law_id
                """
            )
            for row in cursor:
                score = score_article(row, query, terms)
                if score <= 0:
                    continue

                candidates.append(
                    (
                        score,
                        {
                            "law_name": row["law_name"],
                            "article_number": row["article_number"],
                            "content": row["content"],
                            "category": row["category"],
                            "url": row["url"],
                            "cli": row["cli"],
                        },
                    )
                )

        candidates.sort(
            key=lambda item: (
                -item[0],
                len(item[1]["law_name"]),
                len(item[1]["content"]),
            )
        )
        selected = [item[1] for item in candidates[:safe_limit]]

        result["success"] = bool(selected)
        result["message"] = "找到相关法条" if selected else "未检索到相关法条,请调整输入的描述"
        result["data"] = selected
        result["total_count"] = len(candidates)
        result["returned_count"] = len(selected)
        result["search_time"] = time.time() - start_time
        return json.dumps(result, ensure_ascii=False)

    def link_search(self, message: str, limit: int = 5) -> str:
        start_time = time.time()
        message = trim_text(message, MAX_QUERY_CHARS)
        safe_limit = normalize_limit(limit)
        references: List[Dict[str, str]] = []
        seen = set()

        for title, number in extract_quoted_citations(message):
            exact = json.loads(self.exact_search(title, number))
            if not exact.get("success"):
                continue
            data = exact.get("data") or {}
            key = (data.get("law_name", ""), data.get("article_number", ""))
            if key in seen:
                continue
            seen.add(key)
            references.append(
                {
                    "title": data.get("law_name", ""),
                    "article_number": data.get("article_number", ""),
                    "url": data.get("url", ""),
                    "content": data.get("content", ""),
                }
            )

        for title, number in self._extract_unquoted_citations(message, safe_limit):
            exact = json.loads(self.exact_search(title, number))
            if not exact.get("success"):
                continue
            data = exact.get("data") or {}
            key = (data.get("law_name", ""), data.get("article_number", ""))
            if key in seen:
                continue
            seen.add(key)
            references.append(
                {
                    "title": data.get("law_name", ""),
                    "article_number": data.get("article_number", ""),
                    "url": data.get("url", ""),
                    "content": data.get("content", ""),
                }
            )

        if not references:
            for law_name, url in self._find_law_mentions(message, safe_limit):
                key = (law_name, "")
                if key in seen:
                    continue
                seen.add(key)
                references.append(
                    {
                        "title": law_name,
                        "article_number": "",
                        "url": url,
                        "content": "",
                    }
                )

        if not references:
            fuzzy = json.loads(self.fuzzy_search(message, safe_limit))
            for item in fuzzy.get("data") or []:
                key = (item.get("law_name", ""), item.get("article_number", ""))
                if key in seen:
                    continue
                seen.add(key)
                references.append(
                    {
                        "title": item.get("law_name", ""),
                        "article_number": item.get("article_number", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", ""),
                    }
                )

        text = format_references(references)
        payload = {
            "success": bool(references),
            "message": "找到相关法规信源" if references else "未找到可匹配的法规信源",
            "text": text,
            "references": references,
            "search_time": time.time() - start_time,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _ensure_built(self) -> None:
        source_manifest = build_source_manifest()
        with BUILD_LOCK:
            if not needs_rebuild(source_manifest):
                return
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            temp_db = DB_PATH.with_suffix(".tmp")
            if temp_db.exists():
                temp_db.unlink()
            build_database(temp_db)
            temp_db.replace(DB_PATH)
            MANIFEST_PATH.write_text(
                json.dumps(source_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _find_law_by_name(self, law_name: str) -> Optional[sqlite3.Row]:
        query = normalize_title(law_name)
        if not query:
            return None

        with closing(self._connect()) as conn:
            exact = conn.execute(
                """
                SELECT laws.*
                FROM law_aliases
                JOIN laws ON laws.id = law_aliases.law_id
                WHERE law_aliases.normalized_alias = ?
                ORDER BY LENGTH(law_aliases.alias) ASC, laws.implement_date DESC
                LIMIT 1
                """,
                (query,),
            ).fetchone()
            if exact:
                return exact

            if len(query) < MIN_PARTIAL_TITLE_CHARS:
                return None

            partial = conn.execute(
                """
                SELECT DISTINCT laws.*
                FROM law_aliases
                JOIN laws ON laws.id = law_aliases.law_id
                WHERE instr(law_aliases.normalized_alias, ?) > 0
                   OR instr(?, law_aliases.normalized_alias) > 0
                ORDER BY LENGTH(law_aliases.alias) ASC, laws.implement_date DESC
                LIMIT 1
                """,
                (query, query),
            ).fetchone()
            return partial

    def _find_law_mentions(self, message: str, limit: int) -> List[Tuple[str, str]]:
        normalized_message = normalize_title(message)
        if not normalized_message:
            return []

        matches: List[Tuple[str, str, int]] = []
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                """
                SELECT laws.law_name, laws.url, law_aliases.alias, law_aliases.normalized_alias
                FROM law_aliases
                JOIN laws ON laws.id = law_aliases.law_id
                WHERE LENGTH(law_aliases.alias) >= 3
                ORDER BY LENGTH(law_aliases.alias) DESC
                """
            )
            seen_titles = set()
            for row in cursor:
                alias = row["normalized_alias"]
                if alias not in normalized_message:
                    continue
                law_name = row["law_name"]
                if law_name in seen_titles:
                    continue
                seen_titles.add(law_name)
                matches.append((law_name, row["url"], len(alias)))
                if len(matches) >= limit:
                    break

        matches.sort(key=lambda item: (-item[2], len(item[0])))
        return [(law_name, url) for law_name, url, _ in matches[:limit]]

    def _extract_unquoted_citations(self, message: str, limit: int) -> List[Tuple[str, str]]:
        citations: List[Tuple[str, str]] = []
        seen = set()
        for match in ARTICLE_NUMBER_RE.finditer(message or ""):
            prefix = (message or "")[max(0, match.start() - 40):match.start()]
            candidates = self._find_law_mentions(prefix, 1)
            if not candidates:
                continue
            title = candidates[0][0]
            number = match.group(0)
            key = (title, number)
            if key in seen:
                continue
            seen.add(key)
            citations.append(key)
            if len(citations) >= limit:
                break
        return citations


def chinese_to_int(value: str) -> Optional[int]:
    if not value:
        return None
    if value.isdigit():
        return int(value)

    total = 0
    section = 0
    number = 0
    for char in value:
        if char in CN_NUM:
            number = CN_NUM[char]
        elif char in CN_UNIT:
            unit = CN_UNIT[char]
            if unit == 10000:
                section = (section + (number or 0)) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number


def normalize_article_number(article_number: str) -> str:
    match = ARTICLE_NUMBER_RE.search((article_number or "").replace(" ", ""))
    if not match:
        return ""
    main = chinese_to_int(match.group("main"))
    sub = chinese_to_int(match.group("sub")) if match.group("sub") else None
    if main is None:
        return ""
    return f"{main}-{sub}" if sub is not None else str(main)


def normalize_title(title: str) -> str:
    text = (title or "").strip()
    text = text.replace("《", "").replace("》", "")
    text = (
        text.replace("（", "(")
        .replace("）", ")")
        .replace("“", "")
        .replace("”", "")
        .replace("‘", "")
        .replace("’", "")
    )
    text = clean_title(text)
    text = text.replace("(", "").replace(")", "")
    text = re.sub(r"[\s\-—_·•:：,，.。/\\]+", "", text)
    return text


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip())


def trim_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    return text[:max_chars]


def normalize_limit(limit: int, default: int = 5) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), MAX_SEARCH_LIMIT)


def clean_title(raw_title: str) -> str:
    title = (raw_title or "").strip()
    title = TITLE_SUFFIX_RE.sub("", title).strip()
    return title


def extract_title(text: str, file_stem: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if line.startswith("URL:"):
            if idx + 1 < len(lines):
                return clean_title(lines[idx + 1])
            break
    fallback = file_stem.replace("_", " ").strip()
    return clean_title(fallback)


def extract_metadata(text: str) -> Dict[str, str]:
    fields = {
        "url": r"^URL:\s*(.+)$",
        "cli": r"^【法宝引证码】\s*(.+)$",
        "effectiveness": r"^时效性：\s*(.+)$",
        "publish_date": r"^公布日期：\s*(.+)$",
        "implement_date": r"^施行日期：\s*(.+)$",
    }
    metadata: Dict[str, str] = {}
    for key, pattern in fields.items():
        match = re.search(pattern, text, re.MULTILINE)
        metadata[key] = match.group(1).strip() if match else ""
    return metadata


def build_aliases(title: str) -> List[str]:
    variants = {title}
    collapsed = FILE_TITLE_PAREN_RE.sub("", title).strip()
    if collapsed:
        variants.add(collapsed)
    no_prefix = re.sub(r"^中华人民共和国", "", collapsed or title).strip()
    if no_prefix:
        variants.add(no_prefix)
    if no_prefix.endswith("法") or no_prefix.endswith("典") or no_prefix.endswith("条例") or no_prefix.endswith("规定"):
        variants.add(no_prefix)
    return sorted({item for item in variants if len(item) >= 2}, key=len)


def extract_articles(text: str) -> List[Tuple[str, str]]:
    matches = list(ARTICLE_HEADER_RE.finditer(text))
    articles: List[Tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = clean_article_content(text[start:end])
        article_number = match.group("number").strip()
        if content:
            articles.append((article_number, content))
    return articles


def clean_article_content(content: str) -> str:
    cleaned_lines = []
    for line in content.splitlines():
        stripped = line.strip().strip("\u3000")
        if not stripped:
            continue
        if stripped in {"展开", "收起", "引用本法"}:
            continue
        if stripped.startswith("法宝联想"):
            break
        if re.match(r"^第[一二三四五六七八九十百千万零〇两0-9]+章", stripped):
            continue
        cleaned_lines.append(stripped)
    return "\n".join(cleaned_lines).strip()


def iter_source_files() -> List[Path]:
    return sorted(
        path
        for path in RAW_DATA_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".txt", ".md"}
    )


def parse_source_file(source_file: Path) -> Optional[SourceLaw]:
    if source_file.suffix.lower() == ".json":
        return parse_json_source_file(source_file)
    return parse_text_source_file(source_file)


def parse_json_source_file(source_file: Path) -> Optional[SourceLaw]:
    payload = json.loads(source_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None

    law_name = clean_title(str(payload.get("law_name") or source_file.stem))
    short_name = clean_title(str(payload.get("short_name") or ""))
    articles = extract_json_articles(payload.get("articles"))
    if not law_name or not articles:
        return None

    metadata = {
        "url": str(payload.get("url") or "").strip(),
        "cli": str(payload.get("cli") or "").strip(),
        "effectiveness": str(payload.get("effectiveness") or "").strip(),
        "publish_date": str(payload.get("publish_date") or "").strip(),
        "implement_date": str(payload.get("implement_date") or "").strip(),
    }
    return SourceLaw(
        law_name=law_name,
        short_name=short_name,
        metadata=metadata,
        articles=articles,
        category=source_file.parent.name,
    )


def extract_json_articles(raw_articles: object) -> List[Tuple[str, str]]:
    articles: List[Tuple[str, str]] = []
    if isinstance(raw_articles, dict):
        for article_number, content in raw_articles.items():
            number = str(article_number or "").strip()
            body = clean_article_content(str(content or ""))
            if number and body:
                articles.append((number, body))
    elif isinstance(raw_articles, list):
        for item in raw_articles:
            if not isinstance(item, dict):
                continue
            number = str(
                item.get("article_number")
                or item.get("number")
                or item.get("title")
                or ""
            ).strip()
            body = clean_article_content(str(item.get("content") or item.get("text") or ""))
            if number and body:
                articles.append((number, body))
    return articles


def parse_text_source_file(source_file: Path) -> Optional[SourceLaw]:
    text = source_file.read_text(encoding="utf-8", errors="ignore")
    law_name = extract_title(text, source_file.stem)
    articles = extract_articles(text)
    if not law_name or not articles:
        return None

    return SourceLaw(
        law_name=law_name,
        short_name="",
        metadata=extract_metadata(text),
        articles=articles,
        category=source_file.parent.name,
    )


def build_source_manifest() -> Dict[str, object]:
    file_paths = iter_source_files()
    digest = hashlib.sha256()
    latest_mtime_ns = 0
    total_size = 0

    for path in file_paths:
        stat = path.stat()
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        total_size += stat.st_size
        relative_path = path.relative_to(RAW_DATA_DIR).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")

    return {
        "schema_version": SCHEMA_VERSION,
        "file_count": len(file_paths),
        "latest_mtime_ns": latest_mtime_ns,
        "total_size": total_size,
        "content_sha256": digest.hexdigest(),
    }


def needs_rebuild(source_manifest: Dict[str, object]) -> bool:
    if not DB_PATH.exists() or not MANIFEST_PATH.exists():
        return True
    try:
        current = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return current != source_manifest


def build_database(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE laws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_key TEXT UNIQUE NOT NULL,
                law_name TEXT NOT NULL,
                short_name TEXT NOT NULL,
                category TEXT NOT NULL,
                url TEXT NOT NULL,
                cli TEXT NOT NULL,
                effectiveness TEXT NOT NULL,
                publish_date TEXT NOT NULL,
                implement_date TEXT NOT NULL
            );

            CREATE TABLE law_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_id INTEGER NOT NULL,
                alias TEXT NOT NULL,
                normalized_alias TEXT NOT NULL,
                FOREIGN KEY(law_id) REFERENCES laws(id) ON DELETE CASCADE
            );

            CREATE TABLE articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_id INTEGER NOT NULL,
                article_number TEXT NOT NULL,
                normalized_article TEXT NOT NULL,
                content TEXT NOT NULL,
                search_blob TEXT NOT NULL,
                FOREIGN KEY(law_id) REFERENCES laws(id) ON DELETE CASCADE
            );

            CREATE INDEX idx_law_aliases_normalized ON law_aliases(normalized_alias);
            CREATE INDEX idx_articles_normalized ON articles(normalized_article);
            """
        )

        for source_file in iter_source_files():
            parsed = parse_source_file(source_file)
            if parsed is None:
                continue

            metadata = parsed.metadata
            effectiveness = metadata.get("effectiveness", "")
            if any(keyword in effectiveness for keyword in SKIP_EFFECTIVENESS_KEYWORDS):
                continue

            title = parsed.law_name

            aliases = build_aliases(title)
            if parsed.short_name and parsed.short_name not in aliases:
                aliases.insert(1 if len(aliases) > 1 else len(aliases), parsed.short_name)
            short_name = parsed.short_name or (aliases[1] if len(aliases) > 1 else aliases[0])
            law_key = source_file.relative_to(RAW_DATA_DIR).as_posix()

            cursor = conn.execute(
                """
                INSERT INTO laws (
                    law_key, law_name, short_name, category, url, cli,
                    effectiveness, publish_date, implement_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    law_key,
                    title,
                    short_name,
                    parsed.category,
                    metadata.get("url", ""),
                    metadata.get("cli", ""),
                    effectiveness,
                    metadata.get("publish_date", ""),
                    metadata.get("implement_date", ""),
                ),
            )
            law_id = cursor.lastrowid

            conn.executemany(
                "INSERT INTO law_aliases (law_id, alias, normalized_alias) VALUES (?, ?, ?)",
                [(law_id, alias, normalize_title(alias)) for alias in aliases],
            )

            article_rows = []
            for article_number, content in parsed.articles:
                normalized_article = normalize_article_number(article_number)
                if not normalized_article:
                    continue
                search_blob = "\n".join(
                    [
                        title,
                        short_name,
                        parsed.category,
                        article_number,
                        content,
                    ]
                )
                article_rows.append(
                    (
                        law_id,
                        article_number,
                        normalized_article,
                        content,
                        search_blob,
                    )
                )

            conn.executemany(
                """
                INSERT INTO articles (
                    law_id, article_number, normalized_article, content, search_blob
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                article_rows,
            )

        conn.commit()
    finally:
        conn.close()


def build_query_terms(query: str) -> List[str]:
    parts = [part for part in re.split(r"[\s,，。；;、/]+", query) if part]
    ordered = []
    seen = set()
    for item in [query, *parts]:
        token = item.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
        if len(ordered) >= MAX_QUERY_TERMS:
            break
        for alias in QUERY_SYNONYMS.get(token, []):
            if alias not in seen:
                seen.add(alias)
                ordered.append(alias)
                if len(ordered) >= MAX_QUERY_TERMS:
                    break
        if len(ordered) >= MAX_QUERY_TERMS:
            break
    return ordered


def score_article(row: sqlite3.Row, query: str, terms: Sequence[str]) -> int:
    search_blob = row["search_blob"]
    compact_blob = search_blob.replace(" ", "")
    compact_query = query.replace(" ", "")
    score = 0
    matched_terms = 0

    if compact_query and compact_query in compact_blob:
        score += 30

    for term in terms:
        compact_term = term.replace(" ", "")
        if len(compact_term) <= 1:
            continue
        count = compact_blob.count(compact_term)
        if not count:
            continue
        matched_terms += 1
        if compact_term in normalize_title(row["law_name"]):
            score += 16 + min(count, 3)
        elif compact_term in row["article_number"]:
            score += 10 + min(count, 2)
        else:
            score += 5 + min(count, 3)
    if matched_terms:
        score += matched_terms * 12
    return score


def extract_quoted_citations(message: str) -> List[Tuple[str, str]]:
    citations = []
    for match in QUOTED_CITATION_RE.finditer(message or ""):
        citations.append((match.group("title"), match.group("number")))
    return citations


def format_references(references: Iterable[Dict[str, str]]) -> str:
    lines = []
    for index, item in enumerate(references, start=1):
        title = item.get("title", "")
        article_number = item.get("article_number", "")
        url = item.get("url", "")
        prefix = f"{index}. 《{title}》{article_number}".strip()
        if url:
            lines.append(f"{prefix}: {url}")
        else:
            lines.append(prefix)
    return "\n".join(lines)


_ENGINE: Optional[LawSearchEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> LawSearchEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = LawSearchEngine()
    return _ENGINE


def law_exact_search(law_name: str, number: str) -> str:
    return get_engine().exact_search(law_name, number)


def law_fuzzy_search(keyword: str, limit: int = 5) -> str:
    return get_engine().fuzzy_search(keyword, limit)


def law_link_search(message: str, limit: int = 5) -> str:
    return get_engine().link_search(message, limit)


if __name__ == "__main__":
    engine = get_engine()
    print(engine.exact_search("民法典", "第七条"))
    print(engine.fuzzy_search("醉驾 处罚 标准 危险驾驶罪", limit=3))
