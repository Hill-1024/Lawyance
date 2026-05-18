"""
模块描述：前端 SPA fallback 路由，必须最后注册。
"""

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse


router = APIRouter()


@router.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)

    dist_dir = os.path.abspath("dist")
    dist_path = os.path.abspath(os.path.join("dist", full_path))

    if not dist_path.startswith(dist_dir + os.sep) and dist_path != dist_dir:
        raise HTTPException(status_code=403, detail="Access denied")

    if os.path.isfile(dist_path):
        return FileResponse(dist_path)
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    return {"message": "Stateless Agent is running."}
