"""
模块描述：大陆法系三国（印度尼西亚 / 泰国 / 越南）法律检索库。

本包只负责本法域的语料清洗、索引与检索，对外暴露《Lawver 管辖库工作协调规范》
§2.1 约定的六个函数；不修改 tools/、mcps.py、function_calling.py、mcp/pkulaw_client.py，
也不自行注册 LLM Tool。

三国条号写法不同（Pasal N / มาตรา N / Điều N），检索入口统一走 normalize_article_key
归一化，调用方无需关心差异。

SQL 约定：所有语句都在 conn.execute() 调用点以字面量写出，且外部输入一律经占位符
参数绑定传入；包含匹配走 SQLite 的 instr() 函数，不构造通配符，也不拼接 SQL 文本。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
DB_PATH = CACHE_DIR / "civil_law.db"
MANIFEST_PATH = CACHE_DIR / "manifest.json"

# 2：articles 增加 source_file 列，增量重建按文件作用域删除条文。
SCHEMA_VERSION = 2
DEFAULT_LIMIT = 5
MAX_SEARCH_LIMIT = 20
MAX_QUERY_CHARS = 500
MAX_CONTENT_CHARS = 4000
# 模糊检索固定 8 个匹配槽位：SQL 字面量始终不变，用户输入只经参数绑定传入。
MAX_TOKENS = 8
MIN_TOKEN_CHARS = 2

# 目录名 → (国家码, 显示名)。jurisdiction 与 country_label 同值（协调规范 §3.3）。
COUNTRIES: Tuple[Tuple[str, str, str], ...] = (
    ("indonesia", "ID", "印度尼西亚"),
    ("thailand", "TH", "泰国"),
    ("vietnam", "VN", "越南"),
)

# 中文通称别名：仅用于提升中文提问的召回，属命名对照，不是官方译本，
# 不得据此替代原文（协调规范 §6.1）。
CHINESE_ALIASES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("ID", "Kitab Undang-Undang Hukum Perdata",
     ("印尼民法典", "印度尼西亚民法典", "民法典", "kuhperdata")),
    ("ID", "Kitab Undang-Undang Hukum Pidana",
     ("印尼刑法典", "印度尼西亚刑法典", "刑法典", "kuhp")),
    ("ID", "Ketenagakerjaan", ("印尼劳动法", "印度尼西亚劳动法", "劳动法")),
    ("TH", "ประมวลกฎหมายแพ่งและพาณิชย์",
     ("泰国民商法典", "民商法典", "泰国民法典", "民法典", "ccc")),
    ("TH", "ประมวลกฎหมายวิธีพิจารณาความแพ่ง",
     ("泰国民事诉讼法典", "民事诉讼法典", "民诉法典")),
    ("TH", "ประมวลกฎหมายวิธีพิจารณาความอาญา",
     ("泰国刑事诉讼法典", "刑事诉讼法典", "刑诉法典")),
    ("TH", "ประมวลกฎหมายอาญา", ("泰国刑法典", "刑法典")),
    ("TH", "ประมวลรัษฎากร", ("泰国税法典", "税法典")),
    ("TH", "คุ้มครองเด็ก", ("泰国儿童保护法", "儿童保护法")),
    ("TH", "ลิขสิทธิ์", ("泰国著作权法", "著作权法", "版权法")),
    ("VN", "Bộ luật Dân sự", ("越南民法典", "民法典", "blds")),
    ("VN", "Bộ luật Hình sự", ("越南刑法典", "刑法典", "blhs")),
    ("VN", "Bộ luật Lao động", ("越南劳动法典", "越南劳动法", "劳动法典", "劳动法", "blld")),
    ("VN", "Bộ luật Tố tụng dân sự", ("越南民事诉讼法典", "民事诉讼法典", "民诉法典", "blttds")),
    ("VN", "Bộ luật Tố tụng hình sự", ("越南刑事诉讼法典", "刑事诉讼法典", "刑诉法典", "bltths")),
    ("VN", "Luật Tố tụng hành chính", ("越南行政诉讼法", "行政诉讼法")),
)

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_ARTICLE_CORE_RE = re.compile(r"(\d+)\s*([a-zA-Z])?")
_COMPACT_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff\u0e00-\u0e7f]+")
_WHITESPACE_RE = re.compile(r"\s+")

# 自然语言引用抽取：中文书名号、三国各自的条号写法。
_QUOTED_RE = re.compile(r"《([^》\n]{2,80})》\s*第\s*([0-9一二三四五六七八九十百千零〇两]+)\s*条")
_CN_ARTICLE_RE = re.compile(r"第\s*([0-9一二三四五六七八九十百千零〇两]+)\s*条")
_ARTICLE_MENTION_RE = re.compile(
    r"(?:pasal|มาตรา|Điều|điều|Dieu)\s*([0-9๐-๙]+[a-zA-Z]?)", re.IGNORECASE
)

_CN_NUM = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}

_BUILD_LOCK = threading.Lock()
_ENGINE: Optional["CivilLawSearchEngine"] = None
_ENGINE_LOCK = threading.Lock()

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


@contextmanager
def _build_file_lock():
    """跨进程建库锁。

    增量重建是**就地改库**（不像全量那样写临时文件再替换），两个进程同时写同一个库
    会互相破坏。线程锁只能管住本进程，这里再要一把文件锁。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = CACHE_DIR / "build.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        if handle.tell() == 0:
            handle.write("lock")
            handle.flush()
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


# ── 归一化工具 ──────────────────────────────────────────────────────────

def chinese_to_int(value: str) -> Optional[int]:
    """把「一百二十三」这类中文数字转成 int；纯数字直接解析。"""
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in _CN_NUM:
            number = _CN_NUM[char]
        elif char in _CN_UNIT:
            section += (number or 1) * _CN_UNIT[char]
            number = 0
        else:
            return None
    return total + section + number


_ROMAN_VALUES = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                 (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
# 文本在归一化时已转小写，这里必须带 IGNORECASE，否则 Pasal I 这类罗马数字条号匹配不到。
_ROMAN_RE = re.compile(r"(?<![A-Za-z])([IVXLCDM]{1,7})(?![A-Za-z])", re.IGNORECASE)


def _int_to_roman(value: int) -> str:
    out = []
    for amount, symbol in _ROMAN_VALUES:
        while value >= amount:
            out.append(symbol)
            value -= amount
    return "".join(out)


def _roman_to_int(text: str) -> Optional[int]:
    """严格解析罗马数字：只接受 1..50，且必须能反向回写一致。

    不加这条约束，正文里的 MIX、DIV 之类字母序列会被当成数字。
    """
    upper = text.upper()
    total = 0
    index = 0
    for amount, symbol in _ROMAN_VALUES:
        while upper.startswith(symbol, index):
            total += amount
            index += len(symbol)
    if index != len(upper) or not 1 <= total <= 50:
        return None
    return total if _int_to_roman(total) == upper else None


def normalize_article_key(value: str) -> str:
    """把 Pasal 12 / มาตรา ๑๒ / Điều 217a / 第12条 统一成可比较的键（12 / 12 / 217a / 12）。

    印尼的总统决定书（KEPPRES/INPRES）常用罗马数字条号（Pasal I、Pasal II），
    没有阿拉伯数字时回落到罗马数字解析，否则这些条文会被整批丢弃。
    """
    text = str(value or "").translate(_THAI_DIGITS).strip().lower()
    if not text:
        return ""
    match = _ARTICLE_CORE_RE.search(text)
    if match:
        number = int(match.group(1))
        suffix = (match.group(2) or "").lower()
        return f"{number}{suffix}"
    roman = _ROMAN_RE.search(text)
    if roman:
        value_int = _roman_to_int(roman.group(1))
        if value_int is not None:
            return str(value_int)
    return ""


def compact_text(value: str) -> str:
    """压掉空格与标点，只保留字母、数字、汉字与泰文，用于法名比对。"""
    text = str(value or "").lower().translate(_THAI_DIGITS)
    return _COMPACT_RE.sub("", text)


def trim_text(value: str, max_chars: int) -> str:
    text = str(value or "")
    return text if len(text) <= max_chars else text[:max_chars]


def normalize_limit(limit: Any, default: int = DEFAULT_LIMIT) -> int:
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        return default
    if parsed < 1:
        return default
    return min(parsed, MAX_SEARCH_LIMIT)


def split_tokens(query: str) -> List[str]:
    """切检索词。中文/泰文按字切，拉丁文按词切，统一去重后截断到固定槽位。"""
    raw = _WHITESPACE_RE.split(trim_text(query, MAX_QUERY_CHARS).lower())
    tokens: List[str] = []
    for chunk in raw:
        if not chunk:
            continue
        if re.search(r"[\u4e00-\u9fff\u0e00-\u0e7f]", chunk):
            tokens.append(chunk)
            tokens.extend(ch for ch in chunk if len(ch) >= MIN_TOKEN_CHARS)
        else:
            tokens.append(chunk)
    seen = set()
    ordered = []
    for token in tokens:
        token = token.strip()
        if len(token) < MIN_TOKEN_CHARS or token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered[:MAX_TOKENS]


def detect_country(text: str) -> str:
    """从提问里识别国家。识别不出返回空串（不过滤）。"""
    raw = str(text or "")
    lowered = raw.lower()
    # 短别名（印尼）与全称一并识别
    chinese_aliases = {
        "ID": ("印度尼西亚", "印尼"),
        "TH": ("泰国",),
        "VN": ("越南",),
    }
    for code, aliases in chinese_aliases.items():
        if any(alias in raw for alias in aliases):
            return code
    for _, code, label in COUNTRIES:
        if label in raw:
            return code
    if re.search(r"(?<![a-z])indonesia(?![a-z])", lowered):
        return "ID"
    if re.search(r"(?<![a-z])thailand(?![a-z])", lowered):
        return "TH"
    if re.search(r"(?<![a-z])vietnam(?![a-z])", lowered):
        return "VN"
    return ""


# ── 引擎 ────────────────────────────────────────────────────────────────

class CivilLawSearchEngine:
    """基于 SQLite 的三国法律检索引擎。"""

    def __init__(self) -> None:
        if not DATA_DIR.exists():
            raise ValueError(f"法系语料目录不存在: {DATA_DIR}")
        ensure_civil_law_database_ready()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    # ── 法名解析：依次尝试全名、别名精确、别名包含、法名包含 ──
    def _resolve_law(self, conn: sqlite3.Connection, title: str) -> Optional[sqlite3.Row]:
        key = compact_text(title)
        if not key:
            return None
        row = conn.execute(
            "SELECT id, law_name, country, url FROM laws WHERE law_key = ? LIMIT 1",
            (key,),
        ).fetchone()
        if row is not None:
            return row
        row = conn.execute(
            """
            SELECT l.id, l.law_name, l.country, l.url
            FROM aliases al JOIN laws l ON l.id = al.law_id
            WHERE al.alias = ?
            ORDER BY l.article_count DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if row is not None:
            return row
        # 提问里含有某个别名，例如用户写「印尼民法典第 5 条」
        row = conn.execute(
            """
            SELECT l.id, l.law_name, l.country, l.url
            FROM aliases al JOIN laws l ON l.id = al.law_id
            WHERE instr(?, al.alias) > 0
            ORDER BY length(al.alias) DESC, l.article_count DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if row is not None:
            return row
        # 法名里含有提问文本，例如用户只写了法名的一部分
        return conn.execute(
            """
            SELECT id, law_name, country, url
            FROM laws
            WHERE instr(law_key, ?) > 0
            ORDER BY article_count DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()

    def _find_article_row(
        self, conn: sqlite3.Connection, law_id: int, article_key: str
    ) -> Optional[sqlite3.Row]:
        return conn.execute(
            """
            SELECT a.article_number, a.content, a.url, a.source_id, a.status, a.effective_date,
                   a.language, l.law_name, l.country, l.country_label, l.jurisdiction,
                   l.legal_system
            FROM articles a
            JOIN laws l ON l.id = a.law_id
            WHERE a.law_id = ? AND a.article_key = ? AND a.usable = 1
            ORDER BY a.id
            LIMIT 1
            """,
            (law_id, article_key),
        ).fetchone()

    def _find_law_mentions(
        self, conn: sqlite3.Connection, text: str, limit: int
    ) -> List[Tuple[str, str]]:
        key = compact_text(text)
        if not key:
            return []
        rows = conn.execute(
            """
            SELECT l.law_name, l.url
            FROM aliases al JOIN laws l ON l.id = al.law_id
            WHERE instr(?, al.alias) > 0
            ORDER BY length(al.alias) DESC, l.article_count DESC
            LIMIT ?
            """,
            (key, limit * 2),
        ).fetchall()
        found: List[Tuple[str, str]] = []
        seen = set()
        for row in rows:
            if row["law_name"] in seen:
                continue
            seen.add(row["law_name"])
            found.append((row["law_name"], row["url"] or ""))
            if len(found) >= limit:
                break
        return found

    # ── 精确检索 ──
    def exact_search(self, law_name: str, article_number: str) -> str:
        started = time.time()
        title = trim_text(law_name, MAX_QUERY_CHARS).strip()
        result: Dict[str, Any] = {"success": False, "message": "", "data": None, "search_time": 0.0}
        if not title or not str(article_number or "").strip():
            result["message"] = "法律名称和条号不能为空"
            result["search_time"] = time.time() - started
            return json.dumps(result, ensure_ascii=False)

        article_key = normalize_article_key(article_number)
        if not article_key:
            result["message"] = f"无法识别条号: {article_number}"
            result["search_time"] = time.time() - started
            return json.dumps(result, ensure_ascii=False)

        with closing(self._connect()) as conn:
            law = self._resolve_law(conn, title)
            if law is None:
                result["message"] = f"未找到法律: {title}"
                result["search_time"] = time.time() - started
                return json.dumps(result, ensure_ascii=False)
            row = self._find_article_row(conn, law["id"], article_key)

        if row is None:
            result["message"] = f"未找到法条: {law['law_name']} {article_number}"
            result["search_time"] = time.time() - started
            return json.dumps(result, ensure_ascii=False)

        result["success"] = True
        result["message"] = "找到匹配的法条"
        result["data"] = _row_to_hit(row)
        result["search_time"] = time.time() - started
        return json.dumps(result, ensure_ascii=False)

    # ── 模糊检索 ──
    def fuzzy_search(self, query: str, limit: int = DEFAULT_LIMIT) -> str:
        started = time.time()
        safe_limit = normalize_limit(limit)
        result: Dict[str, Any] = {
            "success": False, "message": "", "data": [],
            "total_count": 0, "returned_count": 0, "search_time": 0.0,
        }
        text = trim_text(query, MAX_QUERY_CHARS).strip()
        if not text:
            result["message"] = "检索关键词不能为空"
            result["search_time"] = time.time() - started
            return json.dumps(result, ensure_ascii=False)

        tokens = split_tokens(text)
        if not tokens:
            result["message"] = "检索关键词过短，请补充更具体的描述"
            result["search_time"] = time.time() - started
            return json.dumps(result, ensure_ascii=False)

        country = detect_country(text)
        # 每个检索词占两个槽位（小文本 search_blob 优先，再扫正文），不足的补哨兵值。
        flat: List[str] = []
        for token in tokens:
            flat.extend((token, token))
        flat.extend(["\u0000"] * (MAX_TOKENS * 2 - len(flat)))
        slots = tuple(flat)

        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.article_number, a.content, a.url, a.source_id, a.status,
                       a.effective_date, a.language, a.search_blob, l.law_name, l.country,
                       l.country_label, l.jurisdiction, l.legal_system
                FROM articles a
                JOIN laws l ON l.id = a.law_id
                WHERE a.usable = 1
                  AND (? = '' OR l.country = ?)
                  AND (instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0
                       OR instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0
                       OR instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0
                       OR instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0
                       OR instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0
                       OR instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0
                       OR instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0
                       OR instr(a.search_blob, ?) > 0 OR instr(a.content, ?) > 0)
                LIMIT 3000
                """,
                (country, country) + slots,
            ).fetchall()

        lowered = text.lower()
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for row in rows:
            score = _score_hit(row, tokens, lowered)
            if score <= 0:
                continue
            scored.append((score, _row_to_hit(row)))

        scored.sort(key=lambda item: (-item[0], len(item[1]["law_name"]), len(item[1]["content"])))
        selected = [hit for _, hit in scored[:safe_limit]]

        result["success"] = bool(selected)
        result["message"] = f"检索到 {len(scored)} 条相关法条" if selected else "未检索到相关法条"
        result["data"] = selected
        result["total_count"] = len(scored)
        result["returned_count"] = len(selected)
        result["search_time"] = time.time() - started
        return json.dumps(result, ensure_ascii=False)

    # ── 关联检索 ──
    def link_search(self, message: str, limit: int = DEFAULT_LIMIT) -> str:
        started = time.time()
        safe_limit = normalize_limit(limit)
        text = trim_text(message, MAX_QUERY_CHARS).strip()
        result: Dict[str, Any] = {
            "success": False, "message": "", "text": "", "references": [],
            "data": [], "search_time": 0.0,
        }
        if not text:
            result["message"] = "待解析文本不能为空"
            result["search_time"] = time.time() - started
            return json.dumps(result, ensure_ascii=False)

        references: List[Dict[str, Any]] = []
        hits: List[Dict[str, Any]] = []
        seen: set = set()

        with closing(self._connect()) as conn:
            # 中文写法「印尼民法典第 1 条」抽不出法名，用整句里出现的法名兜底。
            mentioned = self._find_law_mentions(conn, text, 1)
            default_law = mentioned[0][0] if mentioned else ""

            window_start = 0
            for title, number, position, end in _extract_citations(text):
                law = None
                if title:
                    law = self._resolve_law(conn, title)
                if law is None:
                    # 裸写法「印尼民法典第 1 条」没有书名号，取上一个引用结束到本条号之间
                    # 的一小段找法名。窗口必须掐掉前一个引用，否则会解析成前一部法律。
                    window = text[window_start:position]
                    if window.strip():
                        law = self._resolve_law(conn, window[-40:])
                if law is None and default_law:
                    law = self._resolve_law(conn, default_law)
                window_start = end
                if law is None:
                    continue
                row = self._find_article_row(conn, law["id"], normalize_article_key(number))
                if row is None:
                    continue
                dedup = (row["law_name"], row["article_number"])
                if dedup in seen:
                    continue
                seen.add(dedup)
                hit = _row_to_hit(row)
                hits.append(hit)
                references.append(_to_reference(hit))
                if len(hits) >= safe_limit:
                    break

            if not hits:
                for law_name, url in self._find_law_mentions(conn, text, safe_limit):
                    dedup = (law_name, "")
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    references.append({
                        "title": law_name, "article_number": "", "url": url, "content": "",
                    })

        if not references:
            fuzzy = json.loads(self.fuzzy_search(text, safe_limit))
            for hit in fuzzy.get("data") or []:
                dedup = (hit.get("law_name", ""), hit.get("article_number", ""))
                if dedup in seen:
                    continue
                seen.add(dedup)
                hits.append(hit)
                references.append(_to_reference(hit))
            if not references:
                result["message"] = "未找到可匹配的法规信源"
                result["search_time"] = time.time() - started
                return json.dumps(result, ensure_ascii=False)

        result["success"] = True
        result["message"] = "找到相关法规信源"
        result["text"] = _format_references(references)
        result["references"] = references
        result["data"] = hits
        result["search_time"] = time.time() - started
        return json.dumps(result, ensure_ascii=False)


# ── 结果组装 ────────────────────────────────────────────────────────────

def _row_to_hit(row: sqlite3.Row) -> Dict[str, Any]:
    """按协调规范 §3.2/§3.3 组装命中对象：四核心字段 + 统一建议字段。"""
    return {
        "law_name": row["law_name"],
        "article_number": row["article_number"],
        "content": trim_text(row["content"], MAX_CONTENT_CHARS),
        "url": row["url"] or "",
        "source_id": row["source_id"] or "",
        "status": row["status"] or "unknown",
        "effective_date": row["effective_date"] or "",
        "language": row["language"] or "",
        "country": row["country"],
        "country_label": row["country_label"],
        "jurisdiction": row["jurisdiction"],
        "legal_system": row["legal_system"],
    }


def _to_reference(hit: Dict[str, Any]) -> Dict[str, str]:
    return {
        "title": hit["law_name"],
        "article_number": hit["article_number"],
        "url": hit["url"],
        "content": hit["content"],
    }


def _format_references(references: Iterable[Dict[str, str]]) -> str:
    lines = []
    for index, item in enumerate(references, start=1):
        prefix = f"{index}. 《{item.get('title', '')}》{item.get('article_number', '')}".strip()
        url = item.get("url", "")
        lines.append(f"{prefix}: {url}" if url else prefix)
    return "\n".join(lines)


def _score_hit(row: sqlite3.Row, tokens: List[str], lowered_query: str) -> int:
    # 必须和 SQL 的匹配口径一致：search_blob 含法名、条号与别名（中文提问靠别名召回），
    # content 是正文。只读其中任何一个，都会把另一个维度命中的记录判成 0 分丢掉。
    blob = (row["search_blob"] or "").lower()
    content = (row["content"] or "").lower()
    name = (row["law_name"] or "").lower()
    score = 0
    for token in tokens:
        hits = content.count(token)
        if hits:
            score += min(hits, 5) * 2
        if token in blob:
            score += 4
        if token in name:
            score += 6
    if lowered_query and lowered_query in name:
        score += 10
    if row["article_number"] and row["article_number"].lower() in lowered_query:
        score += 8
    return score


def _extract_citations(message: str) -> List[Tuple[str, str, int, int]]:
    """从自然语言里抽（法名, 条号, 起始位置, 结束位置）。

    三类写法都要抽：中文书名号「《法名》第N条」、三国条号「Pasal/มาตรา/Điều N」、
    裸中文条号「第N条」。**不能抽到一种就返回**——一句话里常同时出现多种写法，
    提前返回会静默漏掉后面的引用。结束位置用于给下一个引用切出干净的法名窗口，
    否则窗口里会混进前一个引用的法名。
    """
    citations: List[Tuple[str, str, int, int]] = []
    covered: List[Tuple[int, int]] = []
    for match in _QUOTED_RE.finditer(message):
        number = chinese_to_int(match.group(2))
        if number is not None:
            citations.append((match.group(1), str(number), match.start(), match.end()))
            covered.append((match.start(), match.end()))

    def already_covered(position: int) -> bool:
        return any(start <= position < end for start, end in covered)

    for match in _ARTICLE_MENTION_RE.finditer(message):
        if already_covered(match.start()):
            continue
        citations.append(("", match.group(1).translate(_THAI_DIGITS), match.start(), match.end()))

    for match in _CN_ARTICLE_RE.finditer(message):
        if already_covered(match.start()):
            continue
        number = chinese_to_int(match.group(1))
        if number is not None:
            citations.append(("", str(number), match.start(), match.end()))

    citations.sort(key=lambda item: item[2])
    return citations


# ── 索引构建 ────────────────────────────────────────────────────────────

def _iter_source_files() -> List[Path]:
    files: List[Path] = []
    for folder, _, _ in COUNTRIES:
        country_dir = DATA_DIR / folder
        if not country_dir.exists():
            continue
        files.extend(sorted(country_dir.rglob("*.jsonl")))
    return files


def build_manifest(previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对语料做指纹。文件大小未变时复用上次的内容哈希，避免每次重读 200+MB。"""
    cached_files = (previous or {}).get("files") or {}
    entries: Dict[str, Any] = {}
    digest = hashlib.sha256()
    digest.update(f"schema:{SCHEMA_VERSION}".encode("utf-8"))
    for path in _iter_source_files():
        rel = path.relative_to(DATA_DIR).as_posix()
        size = path.stat().st_size
        previous_entry = cached_files.get(rel)
        if previous_entry and previous_entry.get("size") == size and previous_entry.get("sha256"):
            file_hash = previous_entry["sha256"]
        else:
            hasher = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            file_hash = hasher.hexdigest()
        entries[rel] = {"size": size, "sha256": file_hash}
        digest.update(f"{rel}:{size}:{file_hash}".encode("utf-8"))
    return {
        "schema_version": SCHEMA_VERSION,
        "fingerprint": digest.hexdigest(),
        "files": entries,
        "file_count": len(entries),
    }


def _read_manifest() -> Optional[Dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return None
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _law_aliases(law_name: str) -> List[str]:
    """从法名派生别名：全名、去国名前缀、tentang 之后的标题、编号形式。"""
    aliases = {compact_text(law_name)}
    lowered = law_name.lower()
    marker = " tentang "
    if marker in lowered:
        index = lowered.index(marker)
        aliases.add(compact_text(law_name[index + len(marker):]))
        aliases.add(compact_text(law_name[:index]))
    for suffix in (" nước cộng hòa xã hội chủ nghĩa việt nam", " của bộ ", " của chính phủ"):
        if suffix in lowered:
            aliases.add(compact_text(law_name[: lowered.index(suffix)]))
    aliases.discard("")
    return sorted(aliases)


def _prepare_laws(
    records: Iterable[Dict[str, Any]], default_code: str, default_label: str
) -> Dict[str, Dict[str, str]]:
    """从一批记录里提取法律级元数据，同一 law_key 只留首次出现的。

    全量构建传整个语料，增量构建只传变化的那几个文件——两条路径共用同一份逻辑，
    避免"全量入库正确、增量入库不一致"这类只在维护时才暴露的偏差。
    """
    laws: Dict[str, Dict[str, str]] = {}
    for record in records:
        law_name = str(record.get("law_name") or "").strip()
        law_key = compact_text(law_name)
        if not law_name or not law_key or law_key in laws:
            continue
        laws[law_key] = {
            "law_name": law_name,
            "country": str(record.get("country") or default_code),
            "country_label": str(record.get("country_label") or default_label),
            "jurisdiction": str(record.get("jurisdiction") or default_label),
            "language": str(record.get("language") or ""),
            "legal_system": str(record.get("legal_system") or "civil"),
            "url": str(record.get("url") or ""),
            "source_id": str(record.get("source_id") or ""),
            "status": str(record.get("status") or "unknown"),
            "effective_date": str(record.get("effective_date") or ""),
        }
    return laws


def _collect_all_laws() -> Dict[str, Dict[str, str]]:
    """全量构建用：扫遍语料，建立完整法律清单。"""
    laws: Dict[str, Dict[str, str]] = {}
    for folder, code, label in COUNTRIES:
        country_dir = DATA_DIR / folder
        if not country_dir.exists():
            continue
        for path in sorted(country_dir.rglob("*.jsonl")):
            for law_key, meta in _prepare_laws(_iter_records(path), code, label).items():
                laws.setdefault(law_key, meta)
    return laws


def _law_alias_sets(law_name: str, country: str) -> List[str]:
    """法名派生别名 + 中文通称别名的并集。"""
    aliases = set(_law_aliases(law_name))
    for hint_country, hint_fragment, extra in CHINESE_ALIASES:
        if country == hint_country and hint_fragment.lower() in law_name.lower():
            aliases.update(compact_text(item) for item in extra)
    aliases.discard("")
    return sorted(aliases)


def _iter_records(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _alias_texts(
    laws: Dict[str, Dict[str, str]]
) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """算出每部法的别名集合与拼好的别名文本。

    别名必须在插入条文时就写进检索文本；若改成插入后再用 UPDATE 回填，
    3,200 余次全行重写会把建库从几秒拖到 400 秒。
    """
    alias_names: Dict[str, List[str]] = {}
    alias_text: Dict[str, str] = {}
    for law_key, meta in laws.items():
        names = _law_alias_sets(meta["law_name"], meta["country"])
        alias_names[law_key] = names
        alias_text[law_key] = " ".join(names)
    return alias_names, alias_text


def _ensure_law_rows(
    conn: sqlite3.Connection,
    laws: Dict[str, Dict[str, str]],
    alias_names: Dict[str, List[str]],
) -> Dict[str, int]:
    """插入尚不存在的法律与别名，返回本批法律对应的 law_key -> law_id。

    已存在的法律**不覆盖元数据**（`DO NOTHING`），所以增量重跑同一文件是幂等的。
    """
    law_ids: Dict[str, int] = {}
    for law_key, meta in laws.items():
        conn.execute(
            """
            INSERT INTO laws (law_key, law_name, country, country_label, jurisdiction,
                              language, legal_system, url, source_id, status,
                              effective_date, article_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(law_key) DO NOTHING
            """,
            (
                law_key,
                meta["law_name"],
                meta["country"],
                meta["country_label"],
                meta["jurisdiction"],
                meta["language"],
                meta["legal_system"],
                meta["url"],
                meta["source_id"],
                meta["status"],
                meta["effective_date"],
            ),
        )
        row = conn.execute(
            "SELECT id FROM laws WHERE law_key = ? LIMIT 1", (law_key,)
        ).fetchone()
        if row is not None:
            law_ids[law_key] = row[0]
    for law_key, names in alias_names.items():
        law_id = law_ids.get(law_key)
        if law_id is None:
            continue
        for alias in names:
            conn.execute(
                "INSERT OR IGNORE INTO aliases (alias, law_id) VALUES (?, ?)",
                (alias, law_id),
            )
    return law_ids


def _insert_articles(
    conn: sqlite3.Connection,
    records: Iterable[Dict[str, Any]],
    law_ids: Dict[str, int],
    alias_text: Dict[str, str],
    source_file: str,
) -> Tuple[int, int, Dict[int, int]]:
    """插入一批条文，返回 (入库条数, 跳过条数, law_id -> 可用条数)。

    全量与增量共用，保证两条路径的入库口径完全一致。
    """
    inserted = 0
    skipped = 0
    usable_counts: Dict[int, int] = {}
    for record in records:
        law_name = str(record.get("law_name") or "").strip()
        article_key = normalize_article_key(record.get("article_number"))
        law_key = compact_text(law_name)
        law_id = law_ids.get(law_key)
        if not law_name or not article_key or law_id is None:
            skipped += 1
            continue

        content = str(record.get("content") or "")
        blob = "\n".join((
            law_name,
            str(record.get("article_number") or ""),
            alias_text.get(law_key, ""),
        )).lower()
        usable = 0 if record.get("usable") is False else 1
        if usable:
            usable_counts[law_id] = usable_counts.get(law_id, 0) + 1
        conn.execute(
            """
            INSERT INTO articles (law_id, article_number, article_key, content, url,
                                  source_id, status, effective_date, language, usable,
                                  search_blob, source_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                law_id,
                str(record.get("article_number") or ""),
                article_key,
                content,
                str(record.get("url") or ""),
                str(record.get("source_id") or ""),
                str(record.get("status") or "unknown"),
                str(record.get("effective_date") or ""),
                str(record.get("language") or ""),
                usable,
                blob,
                source_file,
            ),
        )
        inserted += 1
    return inserted, skipped, usable_counts


def _write_database(manifest: Dict[str, Any]) -> Dict[str, int]:
    """全量重建：写临时库再原子替换，中途失败不会留下半成品。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    building_path = DB_PATH.with_suffix(".building")
    if building_path.exists():
        building_path.unlink()

    laws = _collect_all_laws()
    alias_names, alias_text = _alias_texts(laws)

    article_count = 0
    skipped = 0
    usable_counts: Dict[int, int] = {}

    with closing(sqlite3.connect(building_path)) as conn:
        # 这是可重建的派生库，导入期关掉日志与同步等待，避免 8 万条批量写入过慢。
        conn.executescript(
            """
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            CREATE TABLE laws (
                id INTEGER PRIMARY KEY,
                law_key TEXT NOT NULL UNIQUE,
                law_name TEXT NOT NULL,
                country TEXT NOT NULL,
                country_label TEXT NOT NULL,
                jurisdiction TEXT NOT NULL,
                language TEXT NOT NULL,
                legal_system TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unknown',
                effective_date TEXT NOT NULL DEFAULT '',
                article_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX idx_laws_country ON laws(country);
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY,
                law_id INTEGER NOT NULL,
                article_number TEXT NOT NULL,
                article_key TEXT NOT NULL,
                content TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unknown',
                effective_date TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT '',
                usable INTEGER NOT NULL DEFAULT 1,
                search_blob TEXT NOT NULL DEFAULT '',
                source_file TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (law_id) REFERENCES laws(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_articles_law ON articles(law_id, article_key);
            CREATE INDEX idx_articles_usable ON articles(usable);
            CREATE INDEX idx_articles_source ON articles(source_file);
            CREATE TABLE aliases (
                alias TEXT NOT NULL,
                law_id INTEGER NOT NULL,
                PRIMARY KEY (alias, law_id)
            );
            CREATE INDEX idx_aliases_alias ON aliases(alias);
            """
        )

        law_ids = _ensure_law_rows(conn, laws, alias_names)

        for folder, code, label in COUNTRIES:
            country_dir = DATA_DIR / folder
            if not country_dir.exists():
                continue
            for path in sorted(country_dir.rglob("*.jsonl")):
                rel = path.relative_to(DATA_DIR).as_posix()
                inserted, missed, counts = _insert_articles(
                    conn, _iter_records(path), law_ids, alias_text, rel
                )
                article_count += inserted
                skipped += missed
                for law_id, count in counts.items():
                    usable_counts[law_id] = usable_counts.get(law_id, 0) + count

        # 条数在插入时已用 Python 计好。这里不要写成关联子查询回填——实测那会让
        # SQLite 对每部法全表扫一遍 articles，建库从 8 秒变成 420 秒。
        conn.executemany(
            "UPDATE laws SET article_count = ? WHERE id = ?",
            [(count, law_id) for law_id, count in usable_counts.items()],
        )
        conn.commit()

    # os.replace 本身是原子覆盖，不需要先删——先删反而会让并发读者看到"库不存在"。
    building_path.replace(DB_PATH)
    return {"laws": len(laws), "articles": article_count, "skipped": skipped}


def can_incremental_rebuild(cached_manifest: Optional[Dict[str, Any]]) -> bool:
    """增量重建的前提：库在、schema 版本一致、且旧清单里有逐文件记录。"""
    return bool(
        DB_PATH.exists()
        and cached_manifest
        and cached_manifest.get("schema_version") == SCHEMA_VERSION
        and cached_manifest.get("files")
    )


def changed_source_paths(
    source_manifest: Dict[str, Any], cached_manifest: Dict[str, Any]
) -> Tuple[List[str], List[str]]:
    """逐文件比对 (size, sha256)，返回 (内容变了或新增的文件, 已消失的文件)。"""
    source_files = source_manifest.get("files") or {}
    cached_files = cached_manifest.get("files") or {}
    removed = sorted(path for path in cached_files if path not in source_files)
    changed = sorted(
        path for path, entry in source_files.items() if cached_files.get(path) != entry
    )
    return changed, removed


def _resolve_source_path(relative_path: str) -> Path:
    """把清单里的相对路径还原成绝对路径，并校验它没越出语料根目录。"""
    root = DATA_DIR.resolve()
    target = (DATA_DIR / relative_path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"语料路径越界，已拒绝: {relative_path}")
    return target


def _country_hint(relative_path: str) -> Tuple[str, str, str]:
    """从相对路径首段取出国家信息，取不到就退回第一个法域。"""
    folder = relative_path.split("/", 1)[0]
    for entry in COUNTRIES:
        if entry[0] == folder:
            return entry
    return COUNTRIES[0]


def _database_totals() -> Dict[str, int]:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return {
            "laws": conn.execute("SELECT COUNT(*) FROM laws").fetchone()[0],
            "articles": conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        }


def _sync_database_incremental(
    manifest: Dict[str, Any], previous: Dict[str, Any]
) -> Dict[str, int]:
    """就地增量重建：只重解析变化的文件，其余条文一条都不动。

    服务维护后重启时，改一部法律只要几十毫秒，不必等整库 8 秒重建。
    """
    changed, removed = changed_source_paths(manifest, previous)
    stats: Dict[str, int] = {
        "changed_files": len(changed),
        "removed_files": len(removed),
        "deleted_articles": 0,
        "indexed_articles": 0,
        "skipped": 0,
    }
    if not changed and not removed:
        return stats

    targets = list(dict.fromkeys([*removed, *changed]))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 1. 变动的文件按「文件作用域」清干净。不按法律名删，是因为这里不假设
        #    一个文件只装一部法律——将来若把多部法合并进一个文件也不会误删。
        touched: set = set()
        for path in targets:
            for row in conn.execute(
                "SELECT DISTINCT law_id FROM articles WHERE source_file = ?", (path,)
            ).fetchall():
                touched.add(row[0])
            cursor = conn.execute("DELETE FROM articles WHERE source_file = ?", (path,))
            stats["deleted_articles"] += cursor.rowcount or 0

        # 2. 重新解析变化的文件（与全量构建共用同一套入库函数）
        for rel in changed:
            records = list(_iter_records(_resolve_source_path(rel)))
            code, label = _country_hint(rel)[1:]
            laws = _prepare_laws(records, code, label)
            alias_names, alias_text = _alias_texts(laws)
            law_ids = _ensure_law_rows(conn, laws, alias_names)
            inserted, missed, counts = _insert_articles(
                conn, records, law_ids, alias_text, rel
            )
            stats["indexed_articles"] += inserted
            stats["skipped"] += missed
            touched.update(counts)

        # 3. 只重算受影响法律的条数（不做全表关联子查询：实测那样每次 UPDATE
        #    都会全表扫一遍 articles，光回填就要 420 秒）
        for law_id in sorted(touched):
            count = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE law_id = ? AND usable = 1", (law_id,)
            ).fetchone()[0]
            conn.execute("UPDATE laws SET article_count = ? WHERE id = ?", (count, law_id))

        # 4. 清掉已经一条条文都不剩的法律（对应文件被删除的情况）
        orphans = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM laws WHERE id NOT IN (SELECT DISTINCT law_id FROM articles)"
            ).fetchall()
        ]
        for law_id in orphans:
            conn.execute("DELETE FROM aliases WHERE law_id = ?", (law_id,))
            conn.execute("DELETE FROM laws WHERE id = ?", (law_id,))
        stats["removed_laws"] = len(orphans)

        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _state_result(mode: str, fingerprint: str, manifest: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    return {
        "mode": mode,
        "content_sha256": fingerprint,
        "db_path": str(DB_PATH),
        "schema_version": SCHEMA_VERSION,
        "file_count": manifest.get("file_count", 0),
        "law_count": manifest.get("laws", 0),
        "article_count": manifest.get("articles", 0),
        **extra,
    }


def ensure_civil_law_database_ready(*, force_rebuild: bool = False) -> Dict[str, Any]:
    """缺库或语料变化时建索引。返回 dict（不是 JSON 字符串）。

    三种模式（对应协调规范 §3.5 的等价状态）：

    - `reuse`       语料指纹未变，直接用现成的库（实测 0.08 秒）
    - `incremental` 只有部分文件变了，**就地**只重建变化的文件
    - `full`        库缺失 / schema 版本升级 / 强制重建，整库重建

    增量模式是给服务维护用的：改一部法律只要几十毫秒，重启不必等整库重建。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _BUILD_LOCK, _build_file_lock():
        previous = _read_manifest()
        manifest = build_manifest(previous)
        fingerprint = manifest["fingerprint"]

        if (not force_rebuild and DB_PATH.exists() and previous
                and previous.get("fingerprint") == fingerprint):
            return _state_result("reuse", fingerprint, previous)

        if force_rebuild or not can_incremental_rebuild(previous):
            _write_database(manifest)
            mode = "full"
            extra: Dict[str, Any] = {}
        else:
            extra = _sync_database_incremental(manifest, previous or {})
            mode = "incremental"

        manifest.update(_database_totals())
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return _state_result(mode, fingerprint, manifest, **extra)


def reset_engine() -> None:
    """清空单例，便于换库后重新初始化（测试用）。"""
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None


def get_engine() -> CivilLawSearchEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = CivilLawSearchEngine()
    return _ENGINE


# ── 对外统一入口（协调规范 §2.1 约定的六个函数） ────────────────────────

def exact_search(title: str, article_number: str) -> str:
    """法名 + 条款精确命中，返回 JSON 字符串。"""
    return get_engine().exact_search(title, article_number)


def fuzzy_search(query: str, limit: int = DEFAULT_LIMIT) -> str:
    """关键词模糊检索，返回 JSON 字符串。"""
    return get_engine().fuzzy_search(query, limit)


def semantic_search(query: str, limit: int = DEFAULT_LIMIT) -> str:
    """fuzzy_search 的等价别名（规范要求二者行为一致）。"""
    return get_engine().fuzzy_search(query, limit)


def link_search(message: str, limit: int = DEFAULT_LIMIT) -> str:
    """从自然语言抽引用并返回信源，返回 JSON 字符串。"""
    return get_engine().link_search(message, limit)
