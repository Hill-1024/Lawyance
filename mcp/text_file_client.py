"""
模块描述：TXT/Markdown 文件读写工具，读取时过滤可执行嵌入内容。
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from typing import Any


TEXT_FILE_EXTENSIONS = {".txt": "txt", ".md": "md"}
TEXT_FILE_DEFAULT_MAX_CHARS = 30000
TEXT_FILE_MAX_CHARS_CAP = 60000
TEXT_FILE_MAX_READ_BYTES = int(os.getenv("LAWVER_TEXT_FILE_MAX_READ_BYTES", str(2 * 1024 * 1024)))
TEXT_FILE_MAX_WRITE_CHARS = int(os.getenv("LAWVER_TEXT_FILE_MAX_WRITE_CHARS", str(500 * 1024)))

DANGEROUS_BLOCK_TAGS = (
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "applet",
    "frame",
    "frameset",
    "svg",
    "math",
)
DANGEROUS_STANDALONE_TAGS = DANGEROUS_BLOCK_TAGS + ("base", "link", "meta")
DANGEROUS_URI_SCHEMES = ("javascript:", "vbscript:", "data:")

DANGEROUS_BLOCK_RE = re.compile(
    rf"(?is)<\s*({'|'.join(DANGEROUS_BLOCK_TAGS)})\b[^>]*>.*?<\s*/\s*\1\s*>"
)
UNTERMINATED_BLOCK_RE = re.compile(rf"(?is)<\s*({'|'.join(DANGEROUS_BLOCK_TAGS)})\b[^>]*>.*$")
DANGEROUS_TAG_RE = re.compile(rf"(?is)<\s*/?\s*({'|'.join(DANGEROUS_STANDALONE_TAGS)})\b[^>]*>")
EVENT_HANDLER_ATTR_RE = re.compile(r"""(?is)\s+on[\w:-]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""")
URI_ATTR_RE = re.compile(
    r"""(?is)(\s+(?:href|src|xlink:href|formaction|action|poster|data)\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s>]+))"""
)
MARKDOWN_LINK_RE = re.compile(r"(?is)(!?\[[^\]\n]{0,300}\]\()([^)]+)(\))")


@dataclass
class SanitizedText:
    text: str
    findings: list[dict[str, Any]]


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(error_code: str, error_message: str, **extra: Any) -> str:
    payload = {
        "success": False,
        "error_code": error_code,
        "error_message": str(error_message),
    }
    payload.update(extra)
    return _json(payload)


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _file_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    file_type = TEXT_FILE_EXTENSIONS.get(ext)
    if not file_type:
        raise ValueError("仅支持 .txt 和 .md 文件。")
    return file_type


def _decode_text(body: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return body.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace"), "utf-8-replace"


def _normalize_uri(value: str) -> str:
    decoded = html.unescape(str(value or "")).strip().strip("<>").strip("\"'")
    return re.sub(r"[\x00-\x20]+", "", decoded).lower()


def _is_dangerous_uri(value: str) -> bool:
    normalized = _normalize_uri(value)
    return normalized.startswith(DANGEROUS_URI_SCHEMES)


def _add_finding(findings: dict[tuple[str, str], dict[str, Any]], kind: str, value: str, removed_chars: int) -> None:
    key = (kind, value)
    item = findings.setdefault(
        key,
        {
            "kind": kind,
            "value": value,
            "count": 0,
            "removed_chars": 0,
        },
    )
    item["count"] += 1
    item["removed_chars"] += max(0, removed_chars)


def sanitize_txt_md_content(content: str) -> SanitizedText:
    """移除或中和 Markdown/HTML 中可能被渲染执行的内容。"""
    text = str(content or "").replace("\x00", "")
    findings: dict[tuple[str, str], dict[str, Any]] = {}

    def replace_block(match: re.Match[str]) -> str:
        tag = match.group(1).lower()
        _add_finding(findings, "html_block", tag, len(match.group(0)))
        return f"[已过滤可执行内容: {tag} 块]"

    text = DANGEROUS_BLOCK_RE.sub(replace_block, text)
    text = UNTERMINATED_BLOCK_RE.sub(replace_block, text)

    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group(1).lower()
        _add_finding(findings, "html_tag", tag, len(match.group(0)))
        return f"[已过滤可执行内容: {tag} 标签]"

    text = DANGEROUS_TAG_RE.sub(replace_tag, text)

    def replace_event_attr(match: re.Match[str]) -> str:
        attr_name = match.group(0).split("=", 1)[0].strip().lower()
        _add_finding(findings, "html_event_attribute", attr_name, len(match.group(0)))
        return ""

    text = EVENT_HANDLER_ATTR_RE.sub(replace_event_attr, text)

    def replace_uri_attr(match: re.Match[str]) -> str:
        prefix = match.group(1)
        raw_value = next(group for group in match.groups()[1:] if group is not None)
        if not _is_dangerous_uri(raw_value):
            return match.group(0)
        attr_name = prefix.strip().split("=", 1)[0].lower()
        _add_finding(findings, "html_dangerous_uri", attr_name, len(raw_value))
        return f'{prefix}"#lawver-filtered-url"'

    text = URI_ATTR_RE.sub(replace_uri_attr, text)

    def replace_markdown_link(match: re.Match[str]) -> str:
        raw_target = match.group(2).strip()
        first_token = raw_target.split(None, 1)[0].strip("<>")
        if not _is_dangerous_uri(first_token):
            return match.group(0)
        _add_finding(findings, "markdown_dangerous_uri", "link", len(raw_target))
        return f"{match.group(1)}#lawver-filtered-url{match.group(3)}"

    text = MARKDOWN_LINK_RE.sub(replace_markdown_link, text)

    return SanitizedText(text=text, findings=list(findings.values()))


def _bounded_text(text: str, max_chars: int) -> tuple[str, int, bool]:
    text_length = len(text)
    if text_length <= max_chars:
        return text, text_length, False
    suffix = f"\n\n[... content truncated, total length: {text_length} chars ...]"
    clipped = text[: max(0, max_chars - len(suffix))].rstrip() + suffix
    return clipped, text_length, True


def _workspace_display_path(file_path: str) -> str:
    try:
        relative = os.path.relpath(os.path.abspath(file_path), os.getcwd())
    except ValueError:
        return file_path.replace("\\", "/")
    if relative == "." or relative.startswith(".."):
        return file_path.replace("\\", "/")
    return relative.replace("\\", "/")


def txt_md_reader(file_path: str, *, max_chars: int | None = None) -> str:
    """读取工作区中的 txt/md 文件，返回过滤后的文本 JSON。"""
    try:
        file_type = _file_type(file_path)
        max_chars_value = _bounded_int(max_chars, TEXT_FILE_DEFAULT_MAX_CHARS, minimum=1, maximum=TEXT_FILE_MAX_CHARS_CAP)
        with open(file_path, "rb") as f:
            body = f.read(TEXT_FILE_MAX_READ_BYTES + 1)
    except OSError as exc:
        return _error("READ_FAILED", f"文本文件读取失败：{exc.__class__.__name__}")
    except ValueError as exc:
        return _error("UNSUPPORTED_FILE_TYPE", str(exc))

    byte_truncated = len(body) > TEXT_FILE_MAX_READ_BYTES
    if byte_truncated:
        body = body[:TEXT_FILE_MAX_READ_BYTES]

    decoded, encoding = _decode_text(body)
    sanitized = sanitize_txt_md_content(decoded)
    bounded, text_length, char_truncated = _bounded_text(sanitized.text, max_chars_value)
    warning = ""
    if sanitized.findings:
        warning = "已过滤 Markdown/HTML 中的可执行内容或危险链接；返回文本仅表示文件内容。"

    return _json({
        "success": True,
        "file_name": os.path.basename(file_path),
        "file_type": file_type,
        "encoding": encoding,
        "text": bounded,
        "text_length": text_length,
        "truncated": bool(byte_truncated or char_truncated),
        "byte_truncated": byte_truncated,
        "removed_executable_content": sanitized.findings,
        "warning": warning,
    })


def txt_md_writer(file_path: str, content: str) -> str:
    """写入 txt/md 文件；Markdown 内容落盘前先中和可执行嵌入。"""
    try:
        file_type = _file_type(file_path)
    except ValueError as exc:
        return _error("UNSUPPORTED_FILE_TYPE", str(exc))

    raw_content = str(content or "")
    if len(raw_content) > TEXT_FILE_MAX_WRITE_CHARS:
        return _error("CONTENT_TOO_LARGE", f"写入内容超过 {TEXT_FILE_MAX_WRITE_CHARS} 字符上限。")

    sanitized = sanitize_txt_md_content(raw_content)
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(sanitized.text)
    except OSError as exc:
        return _error("WRITE_FAILED", f"文本文件写入失败：{exc.__class__.__name__}")

    return _json({
        "success": True,
        "file_name": os.path.basename(file_path),
        "file_type": file_type,
        "output_path": _workspace_display_path(file_path),
        "text_length": len(sanitized.text),
        "removed_executable_content": sanitized.findings,
        "warning": "写入前已过滤可执行内容或危险链接。" if sanitized.findings else "",
    })
