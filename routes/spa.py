"""
模块描述：前端 SPA fallback 路由，必须最后注册。
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool


router = APIRouter()
DIST_DIR = Path(__file__).resolve().parents[1] / "dist"

# Vite 产物目录，文件名带内容哈希：内容变了文件名就变，可以长期强缓存。
ASSETS_PREFIX = "assets/"
# 其余响应（index.html、sw.js、manifest、固定名图标）必须每次回源校验。缺省不带 Cache-Control
# 时浏览器会按启发式规则缓存 index.html，用户会长期拿到旧页面，而它引用的旧哈希资源在新部署后
# 已被删除，页面就只剩 HTML 骨架。
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


def _resolve_spa_asset(full_path: str) -> tuple[Path, bool] | None:
    """解析 dist 下的真实文件；未命中时回退 index.html，并用第二个返回值标记该回退。"""
    try:
        dist_root = DIST_DIR.resolve(strict=False)
        candidate = (dist_root / full_path).resolve(strict=False)
        if candidate != dist_root and dist_root not in candidate.parents:
            raise PermissionError("path escaped dist root")
        if candidate.is_file():
            return candidate, False
        index_path = (dist_root / "index.html").resolve(strict=False)
        if index_path.parent == dist_root and index_path.is_file():
            return index_path, True
        return None
    except (OSError, RuntimeError, ValueError) as exc:
        raise PermissionError("invalid SPA path") from exc


@router.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)

    try:
        resolved = await run_in_threadpool(_resolve_spa_asset, full_path)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied")
    if resolved is None:
        return {"message": "Stateless Agent is running."}

    asset_path, is_fallback = resolved
    if is_fallback and full_path.startswith(ASSETS_PREFIX):
        # 构建产物目录里的文件不参与 SPA 路由，缺失就是真的缺失。回退成 HTML 会让浏览器
        # 把 HTML 当 JS 解析，表现为「只加载出基本 HTML」且状态码仍是 200，难以排查。
        raise HTTPException(status_code=404)

    cache_control = IMMUTABLE_CACHE if full_path.startswith(ASSETS_PREFIX) else NO_CACHE
    return FileResponse(asset_path, headers={"Cache-Control": cache_control})
