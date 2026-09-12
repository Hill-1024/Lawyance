"""
模块描述：中性媒体共享层，收纳工作区图片读取与多模态 parts 压平工具。

放在仓库根部而不是 services/，是为了让 tools/ 与 agents/ 都能复用它而不必
反向依赖 services/。本模块只依赖 workspace.py。
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from workspace import (
    WORKSPACE_ROOTS,
    WorkspacePathError,
    resolve_workspace_file,
    to_workspace_relative_path,
)


logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MAX_IMAGE_BYTES = int(os.getenv("LAWVER_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))

# 图片按魔数校验，避免改扩展名绕过（历史上仅校验扩展名字符串）。
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)
IMAGE_MIME_EXTENSIONS: dict[str, set[str]] = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/gif": {".gif"},
    "image/bmp": {".bmp"},
    "image/webp": {".webp"},
}

# 单轮对话中通过工具加载图片的次数与总字节上限，避免上下文被 base64 撑爆。
MAX_IMAGE_VIEWS_PER_TURN = 4
MAX_VIEW_TOTAL_BYTES = 16 * 1024 * 1024

# 工具结果中用于向 agent 循环传递图片载荷的保留字段。
IMAGE_SIGNAL_KEY = "__lawver_image__"


def is_image_filename(filename: str | None) -> bool:
    file_ext = os.path.splitext(str(filename or ""))[1].lower()
    return file_ext in ALLOWED_IMAGE_EXTENSIONS


def sniff_image_mime(content: bytes) -> str | None:
    """按魔数返回图片 MIME；webp 需额外校验 RIFF+WEBP 头。"""
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    for signature, mime in _IMAGE_SIGNATURES:
        if content.startswith(signature):
            return mime
    return None


def load_workspace_image(path: str, workspace_scope: str) -> dict[str, Any] | None:
    """读取工作区图片并构造 image_url part。

    返回 {name, path, mime, bytes, part}；路径越界、非图片、过大或读取失败时返回 None。
    """
    normalized = to_workspace_relative_path(path)
    if not normalized:
        logger.warning("图片路径无法归一为工作区相对路径: %s", path)
        return None

    try:
        safe_path = resolve_workspace_file(normalized, workspace_scope, allowed_roots=WORKSPACE_ROOTS)
    except WorkspacePathError as exc:
        logger.warning("图片路径不被工作区允许: %s (%s)", path, exc)
        return None
    except Exception:
        logger.exception("解析图片路径失败: %s", path)
        return None

    if not is_image_filename(safe_path):
        logger.warning("目标不是受支持的图片扩展名: %s", safe_path)
        return None

    try:
        with open(safe_path, "rb") as handle:
            content = handle.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        logger.warning("图片读取失败: %s", safe_path)
        return None

    if not content:
        return None
    if len(content) > MAX_IMAGE_BYTES:
        logger.warning("图片超过 %s 字节上限: %s", MAX_IMAGE_BYTES, safe_path)
        return None

    # 以服务端嗅探到的 MIME 为准，不信任客户端上报值。
    mime = sniff_image_mime(content)
    if mime is None:
        logger.warning("文件内容不是可识别的图片: %s", safe_path)
        return None

    encoded = base64.b64encode(content).decode("ascii")
    return {
        "name": os.path.basename(safe_path),
        "path": normalized,
        "mime": mime,
        "bytes": len(content),
        "part": {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
    }


def flatten_content_to_text(content: Any) -> str:
    """把 parts 列表压成纯文本，用于日志、历史轨迹等只接受字符串的路径。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                chunks.append(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                chunks.append("[图片]")
        return "\n".join(chunk for chunk in chunks if chunk)
    if content is None:
        return ""
    return str(content)
