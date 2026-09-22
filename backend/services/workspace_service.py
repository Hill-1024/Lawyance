"""
模块描述：HTTP 工作区服务，处理上传文件名、用户会话 scope 和缓存目录。

图片魔数/扩展名等中性工具已下沉到 media.py，工作区路径归一化下沉到 workspace.py，
这里做兼容转发，避免 tools/ 反向依赖 services/。
"""

import os
import re
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from media import (
    ALLOWED_IMAGE_EXTENSIONS,  # noqa: F401 - 兼容既有导入
    IMAGE_MIME_EXTENSIONS,
    MAX_IMAGE_BYTES,  # noqa: F401 - 兼容既有导入
    is_image_filename,  # noqa: F401 - 兼容既有导入
    sniff_image_mime,
)
from workspace import (  # noqa: F401 - 兼容既有导入
    WORKSPACE_ROOTS,
    is_within_directory,
    to_workspace_relative_path,
)


ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
ALLOWED_WORKSPACE_EXTENSIONS = ALLOWED_DOCUMENT_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS
MAX_UPLOAD_BYTES = int(os.getenv("LAWVER_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


def validate_image_content(filename: str | None, content: bytes) -> str:
    """校验扩展名与真实魔数一致，返回可用的 MIME。"""
    file_ext = os.path.splitext(str(filename or ""))[1].lower()
    mime = sniff_image_mime(content)
    if mime is None:
        raise HTTPException(
            status_code=400,
            detail="图片内容无法识别，请上传有效的 PNG/JPEG/WEBP/GIF/BMP 文件",
        )
    if file_ext not in IMAGE_MIME_EXTENSIONS.get(mime, set()):
        raise HTTPException(status_code=400, detail="图片扩展名与实际内容不一致，请检查文件")
    return mime


def safe_upload_filename(filename: str | None) -> str:
    raw_name = str(filename or "").strip()
    safe_filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", raw_name)
    safe_filename = os.path.basename(safe_filename).strip()
    if not safe_filename or safe_filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid file name")
    return safe_filename


def validate_workspace_filename(filename: str | None) -> str:
    safe_filename = safe_upload_filename(filename)
    file_ext = os.path.splitext(safe_filename)[1].lower()
    if file_ext not in ALLOWED_WORKSPACE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_WORKSPACE_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed}")
    return safe_filename


async def read_limited_upload(file: UploadFile) -> bytes:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"File size exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit")
    return content


def sanitize_path_component(value: str) -> str:
    encoded = quote(str(value or ""), safe="")
    for char in "._-~":
        encoded = encoded.replace(char, f"%{ord(char):02X}")
    return encoded or "_"


def get_workspace_scope(current_user: str, conversation_id: str) -> str:
    return f"{sanitize_path_component(current_user)}/{sanitize_path_component(conversation_id)}"


def get_workspace_dirs(current_user: str, conversation_id: str) -> tuple[str, str]:
    scope = get_workspace_scope(current_user, conversation_id)
    return os.path.join("TEMP", scope), os.path.join("Result", scope)
