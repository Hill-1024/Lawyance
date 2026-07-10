"""
模块描述：前端 SPA fallback 路由，必须最后注册。
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool


router = APIRouter()
DIST_DIR = Path(__file__).resolve().parents[1] / "dist"


def _resolve_spa_asset(full_path: str) -> Path | None:
    try:
        dist_root = DIST_DIR.resolve(strict=False)
        candidate = (dist_root / full_path).resolve(strict=False)
        if candidate != dist_root and dist_root not in candidate.parents:
            raise PermissionError("path escaped dist root")
        if candidate.is_file():
            return candidate
        index_path = (dist_root / "index.html").resolve(strict=False)
        if index_path.parent == dist_root and index_path.is_file():
            return index_path
        return None
    except (OSError, RuntimeError, ValueError) as exc:
        raise PermissionError("invalid SPA path") from exc


@router.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)

    try:
        asset_path = await run_in_threadpool(_resolve_spa_asset, full_path)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")
    if asset_path is not None:
        return FileResponse(asset_path)
    return {"message": "Stateless Agent is running."}
