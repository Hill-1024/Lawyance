"""
模块描述：前端 SPA fallback 路由，必须最后注册。
"""

import re

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool


router = APIRouter()
DIST_DIR = Path(__file__).resolve().parents[2] / "dist"

# Vite 产物目录，文件名带内容哈希：内容变了文件名就变，可以长期强缓存。
ASSETS_PREFIX = "assets/"
# 其余响应（index.html、sw.js、manifest、固定名图标）必须每次回源校验。缺省不带 Cache-Control
# 时浏览器会按启发式规则缓存 index.html，用户会长期拿到旧页面，而它引用的旧哈希资源在新部署后
# 已被删除，页面就只剩 HTML 骨架。
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"

# 产物用相对资源路径（vite base:'./'），<base> 由部署侧注入：区域网关注入 /cn/ 等，
# 源站自己服务根部署时注入 /，否则深链接（如 /settings/webdav）会把 ./assets 解析到
# /settings/assets 落进本 fallback 拿到 HTML。HTML 规范里多个 <base> 只有第一个生效，
# 而区域网关的注入必须发生在 <head> 顶部（晚于它 preload/脚本就会解析错），因此网关
# 注入的 base 恒在本标签之前、优先级更高——已能工作的网关配置不受本注入影响。
ROOT_BASE_TAG = '<base href="/">'
_HEAD_TAG_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)


def _with_root_base(html: str) -> str:
    # 不做「已有 base 就跳过」的子串检查：产物内联的区域提示脚本文本里就含有
    # <base 字样，子串判断会误判已注入。head 内第一个 base 生效——根部署是本标签，
    # 区域部署是网关插在更前面的 base，语义都正确。
    match = _HEAD_TAG_RE.search(html)
    if match:
        return html[: match.end()] + ROOT_BASE_TAG + html[match.end() :]
    return ROOT_BASE_TAG + html


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
    if is_fallback and "assets/" in f"/{full_path}":
        # 构建产物目录里的文件不参与 SPA 路由，缺失就是真的缺失。回退成 HTML 会让浏览器
        # 把 HTML 当 JS 解析，表现为「只加载出基本 HTML」且状态码仍是 200，难以排查。
        # 嵌套形式（如 /settings/assets/...，来自注入 <base> 前的旧页面）一并拒绝。
        raise HTTPException(status_code=404)

    cache_control = IMMUTABLE_CACHE if full_path.startswith(ASSETS_PREFIX) else NO_CACHE

    if asset_path.name == "index.html":
        html = await run_in_threadpool(asset_path.read_text, "utf-8")
        return Response(
            content=_with_root_base(html),
            media_type="text/html",
            headers={"Cache-Control": cache_control},
        )

    return FileResponse(asset_path, headers={"Cache-Control": cache_control})
