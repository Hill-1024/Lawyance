"""
模块描述：上传、工作区缓存、心跳和下载 API。
"""

import os
import shutil
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from services.auth_dependencies import get_current_user
from services.conversation_state import active_conversations
from services.memory_coordinator import call_memory_tool
from services.workspace_service import (
    get_workspace_dirs,
    get_workspace_scope,
    is_within_directory,
    read_limited_upload,
    sanitize_path_component,
    validate_workspace_filename,
)


router = APIRouter()


@router.get("/api/upload")
async def upload_file_get(current_user: str = Depends(get_current_user)):
    raise HTTPException(status_code=405, detail="Method Not Allowed: Please use POST request to upload files.")


@router.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: str = Form(...),
    current_user: str = Depends(get_current_user),
):
    safe_filename = validate_workspace_filename(file.filename)
    content = await read_limited_upload(file)

    temp_dir, _ = get_workspace_dirs(current_user, conversation_id)
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, safe_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@router.get("/api/workspace/files")
async def list_workspace_files_api(conversation_id: str, current_user: str = Depends(get_current_user)):
    files = []
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    if os.path.exists(temp_dir):
        for f in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, f)
            if os.path.isfile(file_path):
                files.append({"name": f, "path": file_path.replace("\\", "/"), "type": "upload"})

    if os.path.exists(result_dir):
        for f in os.listdir(result_dir):
            file_path = os.path.join(result_dir, f)
            if os.path.isfile(file_path):
                files.append({"name": f, "path": file_path.replace("\\", "/"), "type": "generated"})

    return {"files": files}


@router.post("/api/workspace/restore")
async def restore_workspace_file(
    file: UploadFile = File(...),
    conversation_id: str = Form(...),
    file_type: str = Form(...),
    current_user: str = Depends(get_current_user),
):
    safe_filename = validate_workspace_filename(file.filename)
    content = await read_limited_upload(file)

    if file_type == "upload":
        target_dir, _ = get_workspace_dirs(current_user, conversation_id)
    elif file_type == "generated":
        _, target_dir = get_workspace_dirs(current_user, conversation_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, safe_filename)

    with open(file_path, "wb") as f:
        f.write(content)

    return {"status": "success", "file_path": file_path.replace("\\", "/")}


@router.delete("/api/workspace/file")
async def delete_workspace_file(conversation_id: str, file_path: str, current_user: str = Depends(get_current_user)):
    if not os.path.isabs(file_path):
        target_path = os.path.join(os.getcwd(), file_path)
    else:
        target_path = file_path

    abs_path = os.path.abspath(target_path)
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    allowed_dirs = [temp_dir, result_dir]
    is_allowed = any(is_within_directory(abs_path, d) for d in allowed_dirs)

    if not is_allowed:
        raise HTTPException(status_code=403, detail="File not found or access denied")

    if os.path.exists(abs_path):
        if not os.path.isfile(abs_path):
            raise HTTPException(status_code=400, detail="Target path is not a file")
        try:
            os.remove(abs_path)
            return {"status": "success"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success"}


@router.delete("/api/workspace/{conversation_id}")
async def delete_workspace(conversation_id: str, current_user: str = Depends(get_current_user)):
    temp_dir, result_dir = get_workspace_dirs(current_user, conversation_id)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
    if os.path.exists(result_dir):
        shutil.rmtree(result_dir, ignore_errors=True)
    call_memory_tool("clear_conversation_memory", {}, get_workspace_scope(current_user, conversation_id))

    return {"status": "success"}


@router.post("/api/heartbeat/{conversation_id}")
async def heartbeat(conversation_id: str, current_user: str = Depends(get_current_user)):
    active_conversations[get_workspace_scope(current_user, conversation_id)] = time.time()
    return {"status": "success"}


@router.get("/api/download")
async def download_file(file_path: str, current_user: str = Depends(get_current_user)):
    if not os.path.isabs(file_path):
        target_path = os.path.join(os.getcwd(), file_path)
    else:
        target_path = file_path

    abs_path = os.path.abspath(target_path)
    cwd = os.getcwd()
    safe_user = sanitize_path_component(current_user)
    allowed_dirs = [
        os.path.join(cwd, "TEMP", safe_user),
        os.path.join(cwd, "Result", safe_user),
    ]
    is_allowed = any(is_within_directory(abs_path, d) for d in allowed_dirs)

    if is_allowed and os.path.exists(abs_path) and os.path.isfile(abs_path):
        return FileResponse(path=abs_path, filename=os.path.basename(abs_path))

    raise HTTPException(status_code=403, detail=f"Access denied or file not found: {file_path}")
