"""
模块描述：Block 输入校验器与文书写作软约束校验。
- validate_blocks: 硬校验 block 结构合法性（类型字段、必填值），失败抛 FieldValidationError。
- evaluate_soft_constraints: 软校验文书是否符合 guide 中声明的章节结构，返回 warning 列表（不阻断）。
"""

from __future__ import annotations

import json
from typing import Any

from .composer import SUPPORTED_BLOCK_TYPES
from .errors import FieldValidationError, ManifestValidationError


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

    normalized: list[dict] = []
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
            if not str(block.get("text", "")).strip():
                errors.append(f"blocks[{i}] title 缺少 text")
        elif btype == "heading":
            if not str(block.get("text", "")).strip():
                errors.append(f"blocks[{i}] heading 缺少 text")
            level = block.get("level", 1)
            if not isinstance(level, int) or level < 1 or level > 3:
                errors.append(f"blocks[{i}] heading.level 必须为 1-3 的整数")
        elif btype == "paragraph":
            if not str(block.get("text", "")).strip():
                errors.append(f"blocks[{i}] paragraph 缺少 text")
        elif btype in ("ordered_list", "unordered_list"):
            items = block.get("items")
            if not isinstance(items, list) or len(items) == 0:
                errors.append(f"blocks[{i}] {btype} items 必须为非空数组")
        elif btype == "table":
            header = block.get("header")
            rows = block.get("rows")
            if header is not None and not isinstance(header, list):
                errors.append(f"blocks[{i}] table.header 必须为数组")
            if rows is not None and not isinstance(rows, list):
                errors.append(f"blocks[{i}] table.rows 必须为二维数组")
            elif isinstance(rows, list):
                for j, row in enumerate(rows):
                    if not isinstance(row, list):
                        errors.append(f"blocks[{i}] table.rows[{j}] 必须为数组")
                        break
            if (not header or not isinstance(header, list)) and (not rows or not isinstance(rows, list)):
                errors.append(f"blocks[{i}] table 至少需提供 header 或 rows")
        elif btype == "signature_block":
            lines = block.get("lines")
            has_lines = isinstance(lines, list) and any(str(x).strip() for x in lines)
            has_signer = bool(str(block.get("signer", "")).strip())
            has_entity = bool(str(block.get("entity", "")).strip())
            has_date = bool(str(block.get("date", "")).strip())
            if not (has_lines or has_signer or has_entity or has_date):
                errors.append(f"blocks[{i}] signature_block 必须提供 lines 或 signer/entity/date 中至少一个")

        normalized.append(block)

    if errors:
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

    return warnings
