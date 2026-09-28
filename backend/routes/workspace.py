"""
模块描述：上传、工作区缓存、心跳和下载 API。
"""

import errno
import os
import shutil
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from schemas import MAX_IDENTIFIER_CHARS
from services.auth_dependencies import get_current_user
from services.conversation_state import active_conversations
from services.memory_coordinator import call_memory_tool
from services.workspace_service import (
    MAX_IMAGE_BYTES,
    get_workspace_dirs,
    get_workspace_scope,
    is_image_filename,
    is_within_directory,
    read_limited_upload,
    sanitize_path_component,
    validate_image_content,
    validate_workspace_filename,
)


router = APIRouter()
MAX_WORKSPACE_FILES = 2_000
MAX_FILE_PATH_CHARS = 8_192


class WorkspaceBoundaryError(ValueError):
    pass


class WorkspaceCollectionTooLarge(ValueError):
    pass


def _validate_workspace_dir_path(directory: str) -> str:
    """Validate a conversation directory without following user-controlled links."""
    abs_dir = os.path.abspath(directory)
    user_dir = os.path.dirname(abs_dir)
    storage_root = os.path.dirname(user_dir)
    if os.path.islink(abs_dir) or os.path.islink(user_dir):
        raise WorkspaceBoundaryError("workspace directory cannot be a symbolic link")
    if not is_within_directory(user_dir, storage_root) or not is_within_directory(abs_dir, storage_root):
        raise WorkspaceBoundaryError("workspace directory escaped its storage root")
    return abs_dir


def _ensure_workspace_dir(directory: str) -> str:
    abs_dir = _validate_workspace_dir_path(directory)
    os.makedirs(abs_dir, mode=0o700, exist_ok=True)
    # Re-check after creation to close the common pre-create symlink swap window.
    return _validate_workspace_dir_path(abs_dir)


def _write_workspace_file(directory: str, filename: str, content: bytes) -> str:
    """写入工作区文件，返回**工作区相对路径**（如 TEMP/<scope>/a.png）。

    返回值必须与 _list_workspace_files 保持一致：前端会用它判断文件类型
    （TEMP/ 视为上传、Result/ 视为生成），也会把它作为附件路径交给
    resolve_workspace_file——后者明确拒绝绝对路径。历史实现返回绝对路径，
    导致图片附件被静默跳过、上传文件被误判为生成文件而重复入仓。
    """
    abs_dir = _ensure_workspace_dir(directory)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    file_path = os.path.join(abs_dir, filename)
    try:
        if os.open in os.supports_dir_fd:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            dir_fd = os.open(abs_dir, directory_flags)
            try:
                fd = os.open(filename, flags, 0o600, dir_fd=dir_fd)
            finally:
                os.close(dir_fd)
        else:
            if os.path.islink(file_path):
                raise WorkspaceBoundaryError("workspace file cannot be a symbolic link")
            fd = os.open(file_path, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
    except WorkspaceBoundaryError:
        raise
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise WorkspaceBoundaryError("unsafe workspace path") from exc
        raise
    return os.path.join(directory, filename).replace("\\", "/")


def _list_workspace_files(temp_dir: str, result_dir: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for directory, file_type in ((temp_dir, "upload"), (result_dir, "generated")):
        abs_dir = _validate_workspace_dir_path(directory)
        if not os.path.isdir(abs_dir):
            continue
        with os.scandir(abs_dir) as entries:
            for entry in entries:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                files.append({
                    "name": entry.name,
                    "path": os.path.join(directory, entry.name).replace("\\", "/"),
                    "type": file_type,
                })
                if len(files) > MAX_WORKSPACE_FILES:
                    raise WorkspaceCollectionTooLarge
    return files


def _resolve_allowed_file(file_path: str, allowed_dirs: list[str]) -> str:
    target_path = file_path if os.path.isabs(file_path) else os.path.join(os.getcwd(), file_path)
    abs_path = os.path.abspath(target_path)
    normalized_dirs = [_validate_workspace_dir_path(directory) for directory in allowed_dirs]
    if os.path.islink(abs_path) or not any(is_within_directory(abs_path, directory) for directory in normalized_dirs):
        raise WorkspaceBoundaryError("file is outside the workspace")
    return abs_path


def _delete_regular_file(path: str) -> None:
    if not os.path.lexists(path):
        return
    if os.path.islink(path) or not os.path.isfile(path):
        raise WorkspaceBoundaryError("target is not a regular workspace file")
    os.remove(path)


def _delete_workspace_dirs(directories: tuple[str, str]) -> None:
    validated = tuple(_validate_workspace_dir_path(directory) for directory in directories)
    for directory in validated:
        if os.path.lexists(directory):
            if os.path.islink(directory) or not os.path.isdir(directory):
                raise WorkspaceBoundaryError("unsafe workspace directory")
            shutil.rmtree(directory)


@router.get("/api/upload")
async def upload_file_get(current_user: str = Depends(get_current_user)):
    raise HTTPException(status_code=405, detail="Method Not Allowed: Please use POST request to upload files.")


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: Annotated[str, Form(min_length=1, max_length=MAX_IDENTIFIER_CHARS)] = ...,
    current_user: str = Depends(get_current_user),
):
    safe_filename = validate_workspace_filename(file.filename)
    content = await read_limited_upload(file)
    if is_image_filename(safe_filename):
        # 图片额外按魔数校验并施加更小的体积上限，防止改扩展名绕过。
        validate_image_content(safe_filename, content)
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"图片大小超过 {MAX_IMAGE_BYTES // (1024 * 1024)}MB 上限",
            )

    temp_dir, _ = get_workspace_dirs(current_user, conversation_id)
    try:
        file_path = await run_in_threadpool(_write_workspace_file, temp_dir, safe_filename, content)
    except WorkspaceBoundaryError:
        raise HTTPException(status_code=403, detail="File not found or access denied")
    except OSError:
        raise HTTPException(status_code=500, detail="Unable to store workspace file")

    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@router.get("/api/workspace/files")
async def list_workspace_files_api(
    conversation_id: Annotated[str, Query(min_length=1, max_length=MAX_IDENTIFIER_CHARS)],
    current_user: str = Depends(get_current_user),
):
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    try:
        files = await run_in_threadpool(_list_workspace_files, temp_dir, result_dir)
    except WorkspaceBoundaryError:
        raise HTTPException(status_code=403, detail="File not found or access denied")
    except WorkspaceCollectionTooLarge:
        raise HTTPException(status_code=413, detail="Workspace contains too many files")

    return {"files": files}


@router.post("/api/workspace/restore")
async def restore_workspace_file(
    file: UploadFile = File(...),
    conversation_id: Annotated[str, Form(min_length=1, max_length=MAX_IDENTIFIER_CHARS)] = ...,
    file_type: Annotated[str, Form(pattern="^(upload|generated)$")] = ...,
    current_user: str = Depends(get_current_user),
):
    safe_filename = validate_workspace_filename(file.filename)
    content = await read_limited_upload(file)

    if file_type == "upload":
        target_dir, _ = get_workspace_dirs(current_user, conversation_id)
    elif file_type == "generated":
        _, target_dir = get_workspace_dirs(current_user, conversation_id)
    else:  # Kept as a defensive invariant if FastAPI validation is bypassed internally.
        raise HTTPException(status_code=400, detail="Invalid file type")

    try:
        file_path = await run_in_threadpool(_write_workspace_file, target_dir, safe_filename, content)
    except WorkspaceBoundaryError:
        raise HTTPException(status_code=403, detail="File not found or access denied")
    except OSError:
        raise HTTPException(status_code=500, detail="Unable to restore workspace file")

    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@router.delete("/api/workspace/file")
async def delete_workspace_file(
    conversation_id: Annotated[str, Query(min_length=1, max_length=MAX_IDENTIFIER_CHARS)],
    file_path: Annotated[str, Query(min_length=1, max_length=MAX_FILE_PATH_CHARS)],
    current_user: str = Depends(get_current_user),
):
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    try:
        abs_path = await run_in_threadpool(_resolve_allowed_file, file_path, [temp_dir, result_dir])
        await run_in_threadpool(_delete_regular_file, abs_path)
    except WorkspaceBoundaryError:
        raise HTTPException(status_code=403, detail="File not found or access denied")
    except OSError:
        raise HTTPException(status_code=500, detail="Unable to delete workspace file")

    return {"status": "success"}


@router.delete("/api/workspace/{conversation_id}")
async def delete_workspace(
    conversation_id: Annotated[str, Path(min_length=1, max_length=MAX_IDENTIFIER_CHARS)],
    current_user: str = Depends(get_current_user),
):
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    scope = get_workspace_scope(current_user, conversation_id)
    try:
        # Validate both paths before mutating either one or clearing memory.
        await run_in_threadpool(_delete_workspace_dirs, (temp_dir, result_dir))
        await run_in_threadpool(call_memory_tool, "clear_conversation_memory", {}, scope)
    except WorkspaceBoundaryError:
        raise HTTPException(status_code=403, detail="Workspace not found or access denied")
    except OSError:
        raise HTTPException(status_code=500, detail="Unable to delete workspace")
    active_conversations.pop(scope, None)

    return {"status": "success"}


@router.post("/api/heartbeat/{conversation_id}")
async def heartbeat(
    conversation_id: Annotated[str, Path(min_length=1, max_length=MAX_IDENTIFIER_CHARS)],
    current_user: str = Depends(get_current_user),
):
    active_conversations[get_workspace_scope(current_user, conversation_id)] = time.time()
    return {"status": "success"}


@router.get("/api/download")
async def download_file(
    file_path: Annotated[str, Query(min_length=1, max_length=MAX_FILE_PATH_CHARS)],
    current_user: str = Depends(get_current_user),
):
    # Derive user roots through get_workspace_dirs so alternate configured/test
    # roots share the same authorization logic.
    temp_probe, result_probe = get_workspace_dirs(current_user, "scope-probe")
    allowed_user_dirs = [os.path.dirname(temp_probe), os.path.dirname(result_probe)]
    try:
        abs_path = await run_in_threadpool(_resolve_allowed_file, file_path, allowed_user_dirs)
        is_regular = await run_in_threadpool(
            lambda: os.path.exists(abs_path) and not os.path.islink(abs_path) and os.path.isfile(abs_path)
        )
    except WorkspaceBoundaryError:
        is_regular = False

    if is_regular:
        return FileResponse(path=abs_path, filename=os.path.basename(abs_path))

    raise HTTPException(status_code=403, detail="Access denied or file not found")
