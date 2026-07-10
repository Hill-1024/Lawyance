"""
模块描述：Block 输入校验器与文书写作软约束校验。
- validate_blocks: 硬校验 block 结构合法性（类型字段、必填值），失败抛 FieldValidationError。
- evaluate_soft_constraints: 软校验文书是否符合 guide 中声明的章节结构，返回 warning 列表（不阻断）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .composer import SUPPORTED_BLOCK_TYPES
from .errors import FieldValidationError, ManifestValidationError


# 元评论关键词:LLM 在文书中暴露思绪/起草过程的典型措辞,命中即发软警告
_META_COMMENT_PATTERNS = [
    re.compile(r'我(这样|这么|之所以|在此|在这里)(写|起草|拟定|表述|措辞).{0,20}(是因为|的原因|的目的|意在)'),
    re.compile(r'(以下|下面|这里|此处)(是|为).{0,30}(修改|修订|起草|拟定|调整|完善|草拟)(后|过)?.{0,10}(的)?.{0,15}(正文|内容|版本|结果|诉讼请求|答辩|事实)'),
    re.compile(r'(以上|上述|本文|本稿)(为|是).{0,20}(草拟|草稿|拟稿|初稿|参考).{0,30}(仅供参考)?'),
    re.compile(r'(作者注|笔者注|此处补充|此处需补充|此处可补充|此处建议补充)\s*[:：]'),
    re.compile(r'如有(疑问|问题|不当|遗漏).{0,30}(请|建议).{0,20}(咨询|联系|补充|修改)'),
    re.compile(r'(由于|因为|鉴于)(篇幅|信息|材料|事实)(有限|不足|缺失|不全).{0,30}(暂|此处|此段|此部分)?(略|省略|不展开|从略|待补)'),
]

MAX_BLOCKS = 512
MAX_FIELD_CHARS = 100_000
MAX_TOTAL_TEXT_CHARS = 500_000
MAX_LIST_ITEMS_PER_BLOCK = 1_000
MAX_TOTAL_LIST_ITEMS = 10_000
MAX_TABLE_ROWS = 1_000
MAX_TABLE_COLUMNS = 50
MAX_TOTAL_TABLE_CELLS = 10_000
MAX_SIGNATURE_LINES = 100


def _text_size(value: Any) -> int | None:
    """Return a bounded scalar's text size; containers are invalid cell text."""
    if isinstance(value, (dict, list, tuple, set)):
        return None
    return len(str(value if value is not None else ""))


def _collect_block_text(blocks: list[dict]) -> str:
    """提取所有 block 的可见文本,用于元评论扫描。"""
    parts: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype in ("title", "heading", "paragraph"):
            parts.append(str(b.get("text", "")))
        elif btype in ("ordered_list", "unordered_list"):
            for item in b.get("items") or []:
                parts.append(str(item))
        elif btype == "table":
            for cell in b.get("header") or []:
                parts.append(str(cell))
            for row in b.get("rows") or []:
                for cell in row or []:
                    parts.append(str(cell))
        elif btype == "signature_block":
            for line in b.get("lines") or []:
                parts.append(str(line))
            for key in ("signer", "entity", "date"):
                if b.get(key):
                    parts.append(str(b[key]))
    return "\n".join(parts)


def load_and_validate_guide(guide_path: str) -> dict:
    """读取 guide JSON 并做结构校验，返回规范化 guide。"""
    with open(guide_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return validate_guide(raw)


def validate_guide(raw: dict) -> dict:
    """校验 guide JSON 必填字段，返回规范化 guide。"""
    doc_type = raw.get("doc_type", "(未知)")
    for key in ("doc_type", "category", "description", "guide_markdown"):
        if key not in raw:
            raise ManifestValidationError(doc_type, f"guide 缺少顶层必填字段 '{key}'")
    if not isinstance(raw.get("guide_markdown"), str) or not raw["guide_markdown"].strip():
        raise ManifestValidationError(doc_type, "guide_markdown 必须是非空字符串")

    required_sections = raw.get("required_sections") or []
    if not isinstance(required_sections, list):
        raise ManifestValidationError(doc_type, "required_sections 必须为字符串数组")

    soft_warnings = raw.get("soft_warnings") or []
    if not isinstance(soft_warnings, list):
        raise ManifestValidationError(doc_type, "soft_warnings 必须为字符串数组")

    applicable_law = raw.get("applicable_law") or []

    return {
        "doc_type": raw["doc_type"],
        "category": raw["category"],
        "description": raw["description"],
        "applicable_law": list(applicable_law),
        "required_sections": [str(s) for s in required_sections],
        "soft_warnings": [str(s) for s in soft_warnings],
        "guide_markdown": raw["guide_markdown"],
    }


def validate_blocks(blocks: Any, doc_type: str) -> list[dict]:
    """硬校验 blocks 数组结构。返回规范化 blocks，失败抛 FieldValidationError。"""
    errors: list[str] = []

    if blocks is None:
        raise FieldValidationError(doc_type, ["blocks 不能为空"])
    if not isinstance(blocks, list):
        raise FieldValidationError(doc_type, [f"blocks 必须是数组，实际为 {type(blocks).__name__}"])
    if len(blocks) == 0:
        raise FieldValidationError(doc_type, ["blocks 不能为空数组"])
    if len(blocks) > MAX_BLOCKS:
        raise FieldValidationError(doc_type, [f"blocks 不能超过 {MAX_BLOCKS} 项"])

    normalized: list[dict] = []
    total_text_chars = 0
    total_list_items = 0
    total_table_cells = 0

    def account_text(value: Any, label: str) -> None:
        nonlocal total_text_chars
        if total_text_chars > MAX_TOTAL_TEXT_CHARS:
            return
        size = _text_size(value)
        if size is None:
            errors.append(f"{label} 必须是标量文本")
            return
        if size > MAX_FIELD_CHARS:
            errors.append(f"{label} 不能超过 {MAX_FIELD_CHARS} 个字符")
        total_text_chars += size

    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"blocks[{i}] 必须是对象，实际为 {type(block).__name__}")
            continue
        btype = block.get("type")
        if not btype or not isinstance(btype, str):
            errors.append(f"blocks[{i}] 缺少 type 字段")
            continue
        if btype not in SUPPORTED_BLOCK_TYPES:
            errors.append(
                f"blocks[{i}] type='{btype}' 不在支持范围内 "
                f"(支持: {', '.join(sorted(SUPPORTED_BLOCK_TYPES))})"
            )
            continue

        if btype == "title":
            account_text(block.get("text", ""), f"blocks[{i}].text")
            if not str(block.get("text", "")).strip():
                errors.append(f"blocks[{i}] title 缺少 text")
        elif btype == "heading":
            account_text(block.get("text", ""), f"blocks[{i}].text")
            if not str(block.get("text", "")).strip():
                errors.append(f"blocks[{i}] heading 缺少 text")
            level = block.get("level", 1)
            if isinstance(level, bool) or not isinstance(level, int) or level < 1 or level > 3:
                errors.append(f"blocks[{i}] heading.level 必须为 1-3 的整数")
        elif btype == "paragraph":
            account_text(block.get("text", ""), f"blocks[{i}].text")
            if not str(block.get("text", "")).strip():
                errors.append(f"blocks[{i}] paragraph 缺少 text")
        elif btype in ("ordered_list", "unordered_list"):
            items = block.get("items")
            if not isinstance(items, list) or len(items) == 0:
                errors.append(f"blocks[{i}] {btype} items 必须为非空数组")
            elif len(items) > MAX_LIST_ITEMS_PER_BLOCK:
                errors.append(
                    f"blocks[{i}].items 不能超过 {MAX_LIST_ITEMS_PER_BLOCK} 项"
                )
            else:
                if total_list_items + len(items) > MAX_TOTAL_LIST_ITEMS:
                    total_list_items = MAX_TOTAL_LIST_ITEMS + 1
                else:
                    total_list_items += len(items)
                    for j, item in enumerate(items):
                        account_text(item, f"blocks[{i}].items[{j}]")
        elif btype == "table":
            header = block.get("header")
            rows = block.get("rows")
            if header is not None and not isinstance(header, list):
                errors.append(f"blocks[{i}] table.header 必须为数组")
            elif isinstance(header, list):
                if len(header) > MAX_TABLE_COLUMNS:
                    errors.append(f"blocks[{i}].header 不能超过 {MAX_TABLE_COLUMNS} 列")
                elif total_table_cells + len(header) > MAX_TOTAL_TABLE_CELLS:
                    total_table_cells = MAX_TOTAL_TABLE_CELLS + 1
                else:
                    total_table_cells += len(header)
                    for j, cell in enumerate(header):
                        account_text(cell, f"blocks[{i}].header[{j}]")
            if rows is not None and not isinstance(rows, list):
                errors.append(f"blocks[{i}] table.rows 必须为二维数组")
            elif isinstance(rows, list):
                if len(rows) > MAX_TABLE_ROWS:
                    errors.append(f"blocks[{i}].rows 不能超过 {MAX_TABLE_ROWS} 行")
                else:
                    for j, row in enumerate(rows):
                        if not isinstance(row, list):
                            errors.append(f"blocks[{i}] table.rows[{j}] 必须为数组")
                            break
                        if len(row) > MAX_TABLE_COLUMNS:
                            errors.append(
                                f"blocks[{i}].rows[{j}] 不能超过 {MAX_TABLE_COLUMNS} 列"
                            )
                            continue
                        if total_table_cells + len(row) > MAX_TOTAL_TABLE_CELLS:
                            total_table_cells = MAX_TOTAL_TABLE_CELLS + 1
                            break
                        total_table_cells += len(row)
                        for k, cell in enumerate(row):
                            account_text(cell, f"blocks[{i}].rows[{j}][{k}]")
            if (not header or not isinstance(header, list)) and (not rows or not isinstance(rows, list)):
                errors.append(f"blocks[{i}] table 至少需提供 header 或 rows")
        elif btype == "signature_block":
            lines = block.get("lines")
            if isinstance(lines, list):
                if len(lines) > MAX_SIGNATURE_LINES:
                    errors.append(f"blocks[{i}].lines 不能超过 {MAX_SIGNATURE_LINES} 项")
                else:
                    for j, line in enumerate(lines):
                        account_text(line, f"blocks[{i}].lines[{j}]")
            for key in ("signer", "entity", "date"):
                if block.get(key) is not None:
                    account_text(block.get(key), f"blocks[{i}].{key}")
            has_lines = (
                isinstance(lines, list)
                and len(lines) <= MAX_SIGNATURE_LINES
                and any(str(x).strip() for x in lines)
            )
            has_signer = bool(str(block.get("signer", "")).strip())
            has_entity = bool(str(block.get("entity", "")).strip())
            has_date = bool(str(block.get("date", "")).strip())
            if not (has_lines or has_signer or has_entity or has_date):
                errors.append(f"blocks[{i}] signature_block 必须提供 lines 或 signer/entity/date 中至少一个")

        normalized.append(block)

    if total_list_items > MAX_TOTAL_LIST_ITEMS:
        errors.append(f"列表项总数不能超过 {MAX_TOTAL_LIST_ITEMS}")
    if total_table_cells > MAX_TOTAL_TABLE_CELLS:
        errors.append(f"表格单元格总数不能超过 {MAX_TOTAL_TABLE_CELLS}")
    if total_text_chars > MAX_TOTAL_TEXT_CHARS:
        errors.append(f"文书文本总长度不能超过 {MAX_TOTAL_TEXT_CHARS} 个字符")

    if errors:
        if len(errors) > 50:
            errors = errors[:50] + ["其余校验错误已省略"]
        raise FieldValidationError(doc_type, errors)

    return normalized


def evaluate_soft_constraints(blocks: list[dict], guide: dict) -> list[str]:
    """对照 guide 的 required_sections 与 soft_warnings 评估 blocks 是否符合规范。返回 warning 列表。"""
    warnings: list[str] = []

    has_title = any(b.get("type") == "title" for b in blocks)
    has_signature = any(b.get("type") == "signature_block" for b in blocks)

    if not has_title:
        warnings.append("缺少标题（title 块）。")
    if not has_signature:
        warnings.append("缺少落款（signature_block 块）。")

    headings_text: list[str] = []
    for b in blocks:
        if b.get("type") in ("heading", "title"):
            headings_text.append(str(b.get("text", "")))
        elif b.get("type") == "paragraph":
            # 部分文书将\"此致\"等关键词置于段落而非标题中，纳入检索范围
            text = str(b.get("text", ""))
            if len(text) <= 30:
                headings_text.append(text)
    combined = "\n".join(headings_text)

    missing_sections: list[str] = []
    for section in guide.get("required_sections", []):
        if section not in combined:
            missing_sections.append(section)
    if missing_sections:
        warnings.append(
            "guide 声明的关键章节未在文书中找到：{}".format("、".join(missing_sections))
        )

    full_text = _collect_block_text(blocks)
    meta_hits: list[str] = []
    for pat in _META_COMMENT_PATTERNS:
        m = pat.search(full_text)
        if m:
            sample = m.group(0)
            if len(sample) > 40:
                sample = sample[:40] + "…"
            meta_hits.append(sample)
    if meta_hits:
        warnings.append(
            "检测到 {} 处元评论/起草过程说明(示例:{})。"
            "文书是当事人立场的法律文书,不应包含\"我这样写是因为...\"\"以下是修改后的...\""
            "\"以上为草拟稿\"\"如有疑问请咨询...\"等措辞,请重新撰写相关段落。"
            .format(len(meta_hits), "；".join(meta_hits[:3]))
        )

    return warnings
