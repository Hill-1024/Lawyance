"""
模块描述：结构化文书校验器。
三层校验：manifest 结构校验 → 模板语法预检 → 输入数据校验。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument

from .errors import FieldValidationError, ManifestValidationError

_ALLOWED_FIELD_TYPES = {"string", "text", "list", "boolean", "number"}
_JINJA2_KEYWORDS = {
    "for", "endfor", "if", "endif", "else", "elif",
    "block", "endblock", "extends", "include", "import", "macro", "endmacro",
    "set", "endset", "with", "endwith", "filter", "endfilter", "raw", "endraw",
}
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_manifest(raw: dict) -> dict:
    """校验 manifest.json 结构并返回规范化后的 manifest。"""
    template_name = raw.get("name", "(未知)")

    for required_key in ("name", "version", "category", "description", "fields"):
        if required_key not in raw:
            raise ManifestValidationError(template_name, f"缺少顶层必填字段 '{required_key}'")
    if not isinstance(raw.get("fields"), list) or len(raw["fields"]) == 0:
        raise ManifestValidationError(template_name, "fields 必须是非空数组")

    seen_keys: set[str] = set()
    normalized_fields: list[dict] = []

    for i, field in enumerate(raw["fields"]):
        if not isinstance(field, dict):
            raise ManifestValidationError(template_name, f"fields[{i}] 必须是对象类型")

        key = field.get("key")
        if not key or not isinstance(key, str):
            raise ManifestValidationError(template_name, f"fields[{i}] 缺少 key 属性")

        if not _KEY_PATTERN.match(key):
            raise ManifestValidationError(
                template_name, f"字段 key '{key}' 不合法（仅允许 snake_case，小写字母开头）", key)
        if key in _JINJA2_KEYWORDS:
            raise ManifestValidationError(template_name, f"字段 key '{key}' 与 Jinja2 关键字冲突", key)
        if key in seen_keys:
            raise ManifestValidationError(template_name, f"字段 key '{key}' 重复定义", key)
        seen_keys.add(key)

        ftype = field.get("type", "string")
        if ftype not in _ALLOWED_FIELD_TYPES:
            raise ManifestValidationError(
                template_name,
                f"字段 '{key}' 的 type '{ftype}' 不合法，允许值: {', '.join(sorted(_ALLOWED_FIELD_TYPES))}",
                key)
        if ftype == "list" and "item_schema" not in field:
            raise ManifestValidationError(template_name, f"list 类型字段 '{key}' 缺少 item_schema", key)

        normalized_fields.append({
            "key": key,
            "label": field.get("label", key),
            "type": ftype,
            "required": bool(field.get("required", False)),
            "default": field.get("default"),
            "max_length": field.get("max_length"),
            "item_schema": field.get("item_schema"),
            "description": field.get("description", ""),
        })

    return {
        "name": raw["name"],
        "version": raw["version"],
        "category": raw["category"],
        "description": raw["description"],
        "output_format": raw.get("output_format", "docx"),
        "fields": normalized_fields,
    }


def validate_template_syntax(docx_path: str, manifest: dict) -> list[str]:
    """检查 DOCX 模板占位符与 manifest 字段定义的一致性，返回告警列表。"""
    warnings: list[str] = []
    template_name = manifest["name"]
    declared_keys = {f["key"] for f in manifest["fields"]}
    required_keys = {f["key"] for f in manifest["fields"] if f.get("required")}

    try:
        doc = DocxDocument(docx_path)
    except Exception as e:
        warnings.append("无法打开 DOCX 文件: {}".format(e))
        return warnings

    full_text_parts: list[str] = []
    for para in doc.paragraphs:
        full_text_parts.append(para.text)
    full_text = "\n".join(full_text_parts)

    var_refs = set(re.findall(r"\{\{\s*(\w+)\s*(?:\|[^}]*)?\}\}", full_text))
    for_loop_vars = set(re.findall(r"\{%\s*for\s+\w+\s+in\s+(\w+)\s*%\}", full_text))
    if_vars = set(re.findall(r"\{%\s*if\s+(\w+)\s*%\}", full_text))
    all_template_keys = var_refs | for_loop_vars | if_vars

    undeclared = all_template_keys - declared_keys
    if undeclared:
        warnings.append(
            "模板中存在未在 manifest 中声明的占位符: {}".format(", ".join(sorted(undeclared))))

    missing_in_template = required_keys - all_template_keys
    if missing_in_template:
        warnings.append(
            "manifest 中声明的必填字段在模板中未找到对应占位符: {}".format(", ".join(sorted(missing_in_template))))

    for_tag = re.compile(r"\{%\s*for\s+")
    endfor_tag = re.compile(r"\{%\s*endfor\s*%\}")
    if_tag = re.compile(r"\{%\s*if\s+")
    endif_tag = re.compile(r"\{%\s*endif\s*%\}")

    for_opens = len(for_tag.findall(full_text))
    endfor_closes = len(endfor_tag.findall(full_text))
    if for_opens != endfor_closes:
        warnings.append(
            "{% for %} 标签不匹配: 开放 {} 个, 闭合 {} 个".format(for_opens, endfor_closes))

    if_opens = len(if_tag.findall(full_text))
    if_closes = len(endif_tag.findall(full_text))
    if if_opens != if_closes:
        warnings.append(
            "{% if %} 标签不匹配: 开放 {} 个, 闭合 {} 个".format(if_opens, if_closes))

    return warnings


def validate_input_fields(fields: dict, manifest: dict) -> dict:
    """校验用户输入的字段数据，返回规范化后的字段数据（补默认值）。失败抛 FieldValidationError。"""
    template_name = manifest["name"]
    field_defs = {f["key"]: f for f in manifest["fields"]}
    errors: list[str] = []
    normalized: dict[str, Any] = {}

    unknown_keys = set(fields.keys()) - set(field_defs.keys())
    if unknown_keys:
        errors.append("未知字段: {}".format(", ".join(sorted(unknown_keys))))

    for fdef in manifest["fields"]:
        key = fdef["key"]
        ftype = fdef["type"]
        required = fdef.get("required", False)
        value = fields.get(key)

        if required and (value is None or (isinstance(value, str) and not value.strip())):
            errors.append("'{}'({}) 为必填项".format(fdef["label"], key))
            continue

        if value is None:
            if "default" in fdef:
                normalized[key] = fdef["default"]
            continue

        if ftype in ("string", "text"):
            if not isinstance(value, str):
                errors.append("'{}'({}) 期望字符串类型，实际为 {}".format(
                    fdef["label"], key, type(value).__name__))
                continue
            if fdef.get("max_length") and len(value) > fdef["max_length"]:
                errors.append("'{}'({}) 超出最大长度 {}（当前 {} 字符）".format(
                    fdef["label"], key, fdef["max_length"], len(value)))
            normalized[key] = value

        elif ftype == "list":
            if not isinstance(value, list):
                errors.append("'{}'({}) 期望数组类型，实际为 {}".format(
                    fdef["label"], key, type(value).__name__))
                continue
            normalized[key] = value

        elif ftype == "boolean":
            if not isinstance(value, bool):
                errors.append("'{}'({}) 期望布尔类型，实际为 {}".format(
                    fdef["label"], key, type(value).__name__))
                continue
            normalized[key] = value

        elif ftype == "number":
            if not isinstance(value, (int, float)):
                errors.append("'{}'({}) 期望数字类型，实际为 {}".format(
                    fdef["label"], key, type(value).__name__))
                continue
            normalized[key] = value

    if errors:
        raise FieldValidationError(template_name, errors)

    for fdef in manifest["fields"]:
        key = fdef["key"]
        if key not in normalized and "default" in fdef:
            normalized[key] = fdef["default"]

    return normalized


def load_and_validate_manifest(manifest_path: str) -> dict:
    """读取 manifest.json 文件并校验，返回规范化 manifest。"""
    with open(manifest_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return validate_manifest(raw)
