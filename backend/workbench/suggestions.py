"""首页工作建议：按空间素材标题生成，进程内缓存，模型不可用时降级为静态建议。

素材只取标题与格式，不发送正文；任何异常都不向上抛，避免首页因为模型问题空白。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import json
import os
import re
import time

from sqlalchemy import select

from workbench.store import Item, transaction

_logger = logging.getLogger("lawver.suggestions")

MODEL_TIMEOUT = float(os.environ.get("LAWVER_SUGGESTION_TIMEOUT", "20"))
CACHE_TTL = float(os.environ.get("LAWVER_SUGGESTION_TTL", str(12 * 3600)))
DEGRADED_TTL = float(os.environ.get("LAWVER_SUGGESTION_DEGRADED_TTL", "300"))
REFRESH_INTERVAL = float(os.environ.get("LAWVER_SUGGESTION_REFRESH_INTERVAL", "30"))
MAX_ITEMS = 3
MAX_DOCUMENTS = 6
MAX_CONVERSATIONS = 4

# 模型不可用时的兜底建议，仍随「换一批」轮换，保证首页永远有可点的入口。
FALLBACK = [
    {
        "title": "审查合同风险条款",
        "prompt": "请审查当前材料中的合同条款，列出对我方不利的条款、风险等级和修改建议。",
    },
    {
        "title": "梳理案件时间线",
        "prompt": "请根据现有材料梳理事发时间线，标注每处事实的来源与需要进一步核实的部分。",
    },
    {
        "title": "归纳争议焦点",
        "prompt": "请归纳本案的争议焦点，分别列出双方可能的主张与依据，并标注不确定之处。",
    },
    {
        "title": "起草文书初稿",
        "prompt": "请依据现有材料起草一份文书初稿，并标注需要补充的事实、证据与待确认事项。",
    },
    {
        "title": "核对材料矛盾点",
        "prompt": "请比对各份材料中的陈述，指出相互矛盾之处以及需要补充说明的地方。",
    },
    {
        "title": "生成证据清单",
        "prompt": "请把现有材料整理成证据清单，标注证据名称、来源、证明目的与版本。",
    },
]

SYSTEM_PROMPT = """你在为法律工作台首页生成「工作建议」，帮助用户快速开始一项任务。
输入是用户当前工作区的材料标题清单。请据此提出 3 条具体、可执行、与材料直接相关的建议。
输出要求：
- 只输出 JSON，不要解释、不要代码块之外的任何文字；
- 格式：{"items":[{"title":"…","prompt":"…"}]}
- title：短标签，4-14 个字，用于按钮显示，不要标点结尾；
- prompt：用户点击后直接发送的第一人称指令，20-120 字，指明要处理的材料与期望产出；
- 三条建议角度不重复；材料不足时给出通用的法律工作建议（如审查、梳理、起草）。"""

_cache: dict[str, dict] = {}
_refresh_at: dict[str, float] = {}
_rotation: dict[str, int] = {}


def reset_cache():
    """清空进程内缓存（测试与账号切换后重置用）。"""
    _cache.clear()
    _refresh_at.clear()
    _rotation.clear()


def _scoped(query, project_id: str | None):
    return query.where(Item.project_id == project_id) if project_id else query.where(
        Item.project_id.is_(None)
    )


def _pick(rows, limit: int):
    return [row for row in rows if not row.data.get("archived")][:limit]


def material_digest(user: str, project_id: str | None) -> tuple[str, str]:
    """返回 (指纹, 摘要文本)。指纹含条目 id 与修订号，素材变动即失效缓存。"""
    with transaction() as s:
        documents = _pick(
            s.scalars(
                _scoped(
                    select(Item).where(
                        Item.owner == user,
                        Item.kind == "document",
                        Item.deleted_at.is_(None),
                    ),
                    project_id,
                )
                .order_by(Item.updated_at.desc())
                .limit(MAX_DOCUMENTS * 2)
            ).all(),
            MAX_DOCUMENTS,
        )
        conversations = _pick(
            s.scalars(
                _scoped(
                    select(Item).where(
                        Item.owner == user,
                        Item.kind == "conversation",
                        Item.deleted_at.is_(None),
                    ),
                    project_id,
                )
                .order_by(Item.updated_at.desc())
                .limit(MAX_CONVERSATIONS * 2)
            ).all(),
            MAX_CONVERSATIONS,
        )
        project_title = ""
        if project_id:
            project = s.get(Item, project_id)
            project_title = project.title if project else ""
    signature = hashlib.sha256(
        "|".join(
            f"{item.id}:{item.revision}" for item in [*documents, *conversations]
        ).encode()
    ).hexdigest()
    if not documents and not conversations:
        return signature, ""
    lines = [f"工作区：{project_title or '个人工作区'}"]
    if documents:
        lines.append("文件（最近 %d 篇）：" % len(documents))
        lines += [
            f"- {item.title}（{item.data.get('format') or '未知格式'}，版本 {item.revision}）"
            for item in documents
        ]
    if conversations:
        lines.append("会话（最近 %d 条）：" % len(conversations))
        lines += [f"- {item.title}" for item in conversations]
    lines.append("请给出 3 条建议。")
    return signature, "\n".join(lines)


def _fallback(key: str, advance: bool = False) -> list[dict[str, str]]:
    if advance:
        _rotation[key] = _rotation.get(key, 0) + 1
    start = (_rotation.get(key, 0) * MAX_ITEMS) % len(FALLBACK)
    return [FALLBACK[(start + i) % len(FALLBACK)] for i in range(MAX_ITEMS)]


def _parse(raw: str) -> list[dict[str, str]]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = next((i for i in (text.find("["), text.find("{")) if i >= 0), -1)
    if start < 0:
        return []
    try:
        data = json.JSONDecoder().raw_decode(text[start:])[0]
    except ValueError:
        return []
    entries = data.get("items") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    items, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()[:24]
        prompt = str(entry.get("prompt") or "").strip()[:200]
        if len(title) < 2 or len(prompt) < 4 or title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "prompt": prompt})
        if len(items) >= MAX_ITEMS:
            break
    return items


async def _ask_model(digest: str) -> list[dict[str, str]]:
    from function_calling import call

    message = await call(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": digest},
        ],
        stream=False,
        include_tools=False,
    )
    return _parse(getattr(message, "content", "") or "")


def _prune(now_ts: float):
    if len(_cache) < 200:
        return
    for key in [k for k, v in _cache.items() if v["expires"] <= now_ts]:
        _cache.pop(key, None)


async def generate(user: str, project_id: str | None, refresh: bool = False) -> dict:
    """首页建议的对外入口：**任何**异常都降级成静态建议。

    这是首页的装饰性内容，它失败不该让整个首页报错——尤其是存储层还没就绪、
    模型没配置这类完全与用户无关的原因。
    """
    try:
        return await _generate(user, project_id, refresh)
    except Exception:
        _logger.exception("生成工作建议失败，改用静态建议")
        return {"items": _fallback(f"{user}|{project_id or '*'}", advance=refresh), "degraded": True, "cached": False}


async def _generate(user: str, project_id: str | None, refresh: bool = False) -> dict:
    signature, digest = material_digest(user, project_id)
    key = f"{user}|{project_id or '*'}"
    now_ts = time.time()
    entry = _cache.get(key)
    fresh = bool(entry and entry["expires"] > now_ts and entry["signature"] == signature)
    if fresh and (not refresh or now_ts - _refresh_at.get(key, 0) < REFRESH_INTERVAL):
        return {**entry["value"], "cached": True}
    if not digest:
        value = {"items": _fallback(key, advance=refresh), "degraded": True}
        _cache[key] = {
            "expires": now_ts + DEGRADED_TTL,
            "signature": signature,
            "value": value,
        }
        return {**value, "cached": False}
    _refresh_at[key] = now_ts
    try:
        items = await asyncio.wait_for(_ask_model(digest), timeout=MODEL_TIMEOUT)
    except Exception:
        items = []
    if items:
        value = {"items": items, "degraded": False}
        ttl = CACHE_TTL
    else:
        value = {"items": _fallback(key, advance=True), "degraded": True}
        ttl = DEGRADED_TTL
    _cache[key] = {"expires": now_ts + ttl, "signature": signature, "value": value}
    _prune(now_ts)
    return {**value, "cached": False}
