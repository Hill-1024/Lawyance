"""
模块描述：HTTP 工作区服务，处理上传文件名、用户会话 scope 和缓存目录。
"""

import os
import re
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from workspace import is_within_directory


ALLOWED_WORKSPACE_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
MAX_UPLOAD_BYTES = int(os.getenv("LAWVER_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


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
