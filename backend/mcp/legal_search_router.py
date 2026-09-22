"""按法域把法律检索转发到中国法主库或三套管辖库。

不填 jurisdiction 时仍走中国法，避免改变现有调用。
另提供 resolve_legal_systems：根据提问识别国家与应查法系，供 LLM 再调用检索工具。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from mcp.pkulaw_client import (
    get_article as china_get_article,
    get_linked_content as china_get_linked_content,
    search_article as china_search_article,
)

JURISDICTION_HELP = (
    "法域。不填或中国表示中国法主库。"
    "大陆法系：印尼、泰国、越南的制定法原文。"
    "伊斯兰法系：马来西亚与印尼的伊斯兰金融、清真专题。"
    "普通法系：缅甸、新加坡。"
    "印尼两套都有：问民法典等制定法用大陆法系，问 riba、清真、伊斯兰银行用伊斯兰法系。"
    "跨境或东盟问题时，先调用 resolve_legal_systems 再按返回的 systems 分别检索。"
)

# 展示名（工具参数）→ 内部键
_SYSTEM_LABEL = {
    "china": "中国",
    "civil": "大陆法系",
    "islamic": "伊斯兰法系",
    "common": "普通法系",
}

_ALIASES = {
    "": "china",
    "china": "china",
    "cn": "china",
    "中国": "china",
    "中国法": "china",
    "civil": "civil",
    "大陆法系": "civil",
    "印尼": "civil",
    "印度尼西亚": "civil",
    "indonesia": "civil",
    "泰国": "civil",
    "thailand": "civil",
    "越南": "civil",
    "vietnam": "civil",
    "id": "civil",
    "th": "civil",
    "vn": "civil",
    "islamic": "islamic",
    "伊斯兰": "islamic",
    "伊斯兰法系": "islamic",
    "马来西亚": "islamic",
    "malaysia": "islamic",
    "my": "islamic",
    "common": "common",
    "普通法": "common",
    "普通法系": "common",
    "缅甸": "common",
    "myanmar": "common",
    "新加坡": "common",
    "singapore": "common",
    "mm": "common",
    "sg": "common",
}

# 国家识别：别名 → (ISO, 中文展示名, 英文检索锚点)
_COUNTRY_ALIASES: list[tuple[tuple[str, ...], str, str, str]] = [
    (("中国", "china", "prc", "中华人民共和国"), "CN", "中国", "China"),
    (("印度尼西亚", "印尼", "indonesia", "republik indonesia"), "ID", "印度尼西亚", "Indonesia"),
    (("马来西亚", "malaysia"), "MY", "马来西亚", "Malaysia"),
    (("新加坡", "singapore"), "SG", "新加坡", "Singapore"),
    (("缅甸", "myanmar", "burma"), "MM", "缅甸", "Myanmar"),
    (("泰国", "thailand"), "TH", "泰国", "Thailand"),
    (("越南", "vietnam", "việt nam"), "VN", "越南", "Vietnam"),
]

# 伊斯兰金融 / 清真等主题：印尼在此主题下需同时查伊斯兰库
_ISLAMIC_TOPIC_RE = re.compile(
    r"(伊斯兰|清真|halal|sharia|syariah|riba|利息|银行|bank|"
    r"金融|finance|takaful|wakaf|waqf|sukuk|mudarabah|murabaha)",
    re.IGNORECASE,
)

# 各国默认应查法系；印尼的伊斯兰库按主题追加
_COUNTRY_BASE_SYSTEMS: dict[str, list[str]] = {
    "CN": ["china"],
    "ID": ["civil"],
    "MY": ["islamic"],
    "SG": ["common"],
    "MM": ["common"],
    "TH": ["civil"],
    "VN": ["civil"],
}


def resolve_jurisdiction(value: str | None) -> str:
    key = str(value or "").strip().casefold().replace(" ", "")
    resolved = _ALIASES.get(key)
    if resolved is None:
        raise ValueError(
            "无法识别的法域。请使用：中国、大陆法系、伊斯兰法系、普通法系。"
        )
    return resolved


def detect_countries(question: str) -> list[dict[str, str]]:
    """从提问中识别国家；按别名最长优先，避免短词误伤。"""
    text = str(question or "")
    lowered = text.casefold()
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    ordered = sorted(_COUNTRY_ALIASES, key=lambda item: max(len(a) for a in item[0]), reverse=True)
    for aliases, code, label_zh, label_en in ordered:
        if code in seen:
            continue
        for alias in aliases:
            needle = alias.casefold()
            if needle in lowered or alias in text:
                hits.append(
                    {
                        "country": code,
                        "country_label": label_zh,
                        "country_label_en": label_en,
                    }
                )
                seen.add(code)
                break
    return hits


def _topic_keywords(question: str) -> str:
    """抽出宜放进检索词的主题片段（去掉国家别名与口语壳）。"""
    text = str(question or "").strip()
    for aliases, _, _, _ in _COUNTRY_ALIASES:
        for alias in aliases:
            text = re.sub(re.escape(alias), " ", text, flags=re.IGNORECASE)
    # 去掉常见问句壳，保留核心主题词
    for noise in (
        "要注意什么",
        "需要注意什么",
        "怎么办",
        "如何",
        "怎样",
        "请问",
        "想了解",
        "相关规定",
        "法律风险",
        "合规要求",
    ):
        text = text.replace(noise, " ")
    text = re.sub(r"[？?！!。．,.，、；;：:\s]+", " ", text).strip()
    text = re.sub(r"^(在|对|关于|就)\s*", "", text)
    return text[:120]


def _reason_for(system: str, country: dict[str, str], islamic_topic: bool) -> str:
    code = country["country"]
    label = country["country_label"]
    if system == "civil" and code == "ID":
        return f"{label}国家法属大陆法系；开业、公司、银行监管等制定法查本库"
    if system == "islamic" and code == "ID":
        return f"{label}伊斯兰金融与清真规则经国家立法吸收；银行/金融主题需另查本库"
    if system == "islamic" and code == "MY":
        return f"{label}伊斯兰金融与清真为建库重点"
    if system == "common":
        return f"{label}属普通法系管辖库"
    if system == "civil":
        return f"{label}制定法在大陆法系库"
    if system == "china":
        return "默认中国法主库"
    if islamic_topic:
        return "提问涉及伊斯兰金融或清真主题"
    return f"按 {label} 对应法系检索"


def resolve_legal_systems(question: str) -> str:
    """识别提问涉及的国家与应查法系，并给出建议检索调用。

    不直接查库；LLM 应按返回的 systems 分别调用 search_article / get_article。
    """
    text = str(question or "").strip()
    countries = detect_countries(text)
    islamic_topic = bool(_ISLAMIC_TOPIC_RE.search(text))
    topic = _topic_keywords(text) or text[:80]

    systems: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    def add_system(system_key: str, country: dict[str, str] | None, reason: str) -> None:
        country_code = country["country"] if country else ""
        key = (system_key, country_code)
        if key in seen_keys:
            return
        seen_keys.add(key)
        label_zh = country["country_label"] if country else ""
        label_en = country["country_label_en"] if country else ""
        if system_key == "china":
            query = topic
        elif system_key == "islamic":
            # 伊斯兰库国家过滤认英文名 / ISO；中文提问需带上英文锚点
            query = " ".join(part for part in (label_zh, label_en, topic) if part).strip()
        else:
            query = " ".join(part for part in (label_zh, topic) if part).strip()
        systems.append(
            {
                "jurisdiction": _SYSTEM_LABEL[system_key],
                "country": country_code,
                "country_label": label_zh,
                "reason": reason,
                "suggested_query": query,
            }
        )

    if not countries:
        add_system("china", None, "未识别到跨境国家，默认中国法；若用户明确他国请改写提问后重试")
    else:
        for country in countries:
            code = country["country"]
            for system_key in _COUNTRY_BASE_SYSTEMS.get(code, ["china"]):
                add_system(system_key, country, _reason_for(system_key, country, islamic_topic))
            # 印尼：银行/金融/清真等主题额外查伊斯兰库
            if code == "ID" and islamic_topic:
                add_system("islamic", country, _reason_for("islamic", country, True))
            # 马来西亚提问若只谈普通商事且未触伊斯兰主题，仍查伊斯兰库（该库覆盖 MY 合规）
            # 已在 base systems

    plan = {
        "success": True,
        "question": text,
        "countries": countries,
        "systems": systems,
        "notes": [
            "对 systems 中每一项分别调用 search_article，传入对应 jurisdiction 与 suggested_query。",
            "印尼制定法与伊斯兰金融分属两库，不可只查其一就下结论。",
            "不填 jurisdiction 只会查中国法。",
        ],
    }
    return json.dumps(plan, ensure_ascii=False)

def ensure_civil_law_database_ready(*, force_rebuild: bool = False) -> dict[str, Any]:
    from RAG.civil_law import ensure_civil_law_database_ready as impl

    return impl(force_rebuild=force_rebuild)


def ensure_islamic_database_ready(*, force_rebuild: bool = False) -> dict[str, Any]:
    from RAG.islamic_law import ensure_islamic_database_ready as impl

    return impl(force_rebuild=force_rebuild)


def ensure_common_law_database_ready(*, force_rebuild: bool = False) -> dict[str, Any]:
    from RAG.common_law import ensure_common_law_database_ready as impl

    return impl(force_rebuild=force_rebuild)


def _fail(message: str) -> str:
    return json.dumps({"success": False, "message": message}, ensure_ascii=False)


def _loads(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise TypeError("检索结果不是 JSON 对象")
    return data


def _format_hits(items: list[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        law_name = item.get("law_name", "")
        article_number = item.get("article_number", "")
        content = str(item.get("content") or "")
        url = item.get("url") or ""
        snippet = content if len(content) <= 220 else f"{content[:220]}..."
        source = f"\n来源: {url}" if url else ""
        lines.append(f"{index}. 《{law_name}》{article_number}\n{snippet}{source}")
    return "\n\n".join(lines)


def _call(jurisdiction: str, china: Callable[[], str], other: Callable[[], str]) -> str:
    try:
        system = resolve_jurisdiction(jurisdiction)
    except ValueError as exc:
        return _fail(str(exc))
    if system == "china":
        return china()
    print(f"正在调用法域库:{system}")
    try:
        return other()
    except Exception as exc:
        return _fail(f"法域库检索失败: {exc}")


def _exact(system: str, title: str, number: str) -> str:
    if system == "civil":
        from RAG.civil_law import exact_search
    elif system == "islamic":
        from RAG.islamic_law import exact_search
    else:
        from RAG.common_law import exact_search
    result = _loads(exact_search(title, number))
    if not result.get("success"):
        return _fail(result.get("message") or "未找到匹配的法条内容，请检查法律名称和条号是否正确")
    data = result.get("data") or {}
    content = data.get("content") or ""
    if not content:
        return _fail("未找到匹配的条，请修改查询关键词")
    return json.dumps(
        {
            "success": True,
            "title": data.get("law_name", ""),
            "content": content,
            "url": data.get("url") or "",
            "jurisdiction": system,
        },
        ensure_ascii=False,
    )


def _fuzzy(system: str, text: str) -> str:
    if system == "civil":
        from RAG.civil_law import fuzzy_search as search
    elif system == "islamic":
        from RAG.islamic_law import semantic_search as search
    else:
        from RAG.common_law import fuzzy_search as search
    result = _loads(search(text, 5))
    items = [item for item in (result.get("data") or []) if isinstance(item, dict)]
    if not items:
        return _fail(result.get("message") or "未检索到相关法条,请调整输入的描述")
    return json.dumps(
        {"success": True, "result": _format_hits(items), "jurisdiction": system},
        ensure_ascii=False,
    )


def _link(system: str, message: str) -> str:
    if system == "civil":
        from RAG.civil_law import link_search
    elif system == "islamic":
        from RAG.islamic_law import link_search
    else:
        from RAG.common_law import link_search
    result = _loads(link_search(message, 5))
    if not result.get("success"):
        return _fail(result.get("message") or "未找到可匹配的法规信源")
    return json.dumps(
        {"success": True, "text": result.get("text") or "", "jurisdiction": system},
        ensure_ascii=False,
    )


def get_article(title: str, number: str, jurisdiction: str = "") -> str:
    """按法域精确取一条法条。不填法域时走中国法主库。"""
    return _call(
        jurisdiction,
        lambda: china_get_article(title, number),
        lambda: _exact(resolve_jurisdiction(jurisdiction), title or "", number or ""),
    )


def search_article(text: str, jurisdiction: str = "") -> str:
    """按法域做关键词检索。不填法域时走中国法主库。"""
    return _call(
        jurisdiction,
        lambda: china_search_article(text),
        lambda: _fuzzy(resolve_jurisdiction(jurisdiction), text or ""),
    )


def get_linked_content(message: str, jurisdiction: str = "") -> str:
    """按法域抽取可引用信源。不填法域时走中国法主库。"""
    return _call(
        jurisdiction,
        lambda: china_get_linked_content(message),
        lambda: _link(resolve_jurisdiction(jurisdiction), message or ""),
    )
