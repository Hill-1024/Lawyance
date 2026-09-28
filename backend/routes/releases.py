"""
模块描述：公开 Android APK 版本检测和分发路由。
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from services.release_sync import (
    APK_MIME,
    apk_filename,
    cached_apk_path,
    cached_manifest,
    consume_apk_download_slot,
)


router = APIRouter()


@router.get("/api/releases/android/latest")
async def android_latest_release(request: Request):
    manifest = cached_manifest(request)
    if not manifest:
        raise HTTPException(status_code=503, detail="Android release is not available yet")
    return manifest


@router.get("/api/releases/android/apk")
async def android_apk(request: Request):
    if not consume_apk_download_slot(request):
        return JSONResponse(
            status_code=429,
            content={"detail": "APK download rate limit exceeded. Please retry later."},
            headers={"Retry-After": "60"},
        )

    manifest = cached_manifest(request)
    apk_path = cached_apk_path()
    if not manifest or not apk_path:
        raise HTTPException(status_code=503, detail="Android APK is not available yet")

    return FileResponse(
        path=apk_path,
        media_type=APK_MIME,
        filename=apk_filename(manifest),
    )
