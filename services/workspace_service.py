"""
模块描述：HTTP 工作区服务，处理上传文件名、用户会话 scope 和缓存目录。
"""

import os
import re
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from workspace import is_within_directory


ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
ALLOWED_WORKSPACE_EXTENSIONS = ALLOWED_DOCUMENT_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS
MAX_UPLOAD_BYTES = int(os.getenv("LAWVER_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MAX_IMAGE_BYTES = int(os.getenv("LAWVER_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))

# 图片按魔数校验，避免改扩展名绕过（历史上仅校验扩展名字符串）。
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)
_IMAGE_MIME_EXTENSIONS: dict[str, set[str]] = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/gif": {".gif"},
    "image/bmp": {".bmp"},
    "image/webp": {".webp"},
}


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


def validate_image_content(filename: str | None, content: bytes) -> str:
    """校验扩展名与真实魔数一致，返回可用的 MIME。"""
    file_ext = os.path.splitext(str(filename or ""))[1].lower()
    mime = sniff_image_mime(content)
    if mime is None:
        raise HTTPException(
            status_code=400,
            detail="图片内容无法识别，请上传有效的 PNG/JPEG/WEBP/GIF/BMP 文件",
        )
    if file_ext not in _IMAGE_MIME_EXTENSIONS.get(mime, set()):
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


WORKSPACE_ROOTS = ("TEMP", "Result")


def to_workspace_relative_path(path: str | None) -> str:
    """把任意形态的工作区路径折算成 `TEMP/…` 或 `Result/…` 相对形式。

    上传接口历史版本返回绝对路径，而列表接口、工具读取（resolve_workspace_file）
    和前端附件上传都以上述相对形式为准：绝对路径会被判为越界而静默丢弃，
    也会被前端误判成"生成文件"重复回灌到 Result 工作区。
    这里只做形式归一，越界校验仍由 resolve_workspace_file 按会话 scope 执行。
    """
    candidate = str(path or "").replace("\\", "/").strip()
    if not candidate:
        return ""
    parts = candidate.split("/")
    for root in WORKSPACE_ROOTS:
        if root in parts:
            return "/".join(parts[parts.index(root):])
    return candidate
