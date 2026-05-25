"""
模块描述：Android APK 发布缓存同步、公开版本元数据和下载限流。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Request

from services.app_security import client_ip_for_request


ANDROID_PACKAGE_NAME = "moe.mutsumi.lawver"
ANDROID_PLATFORM = "android"
MANIFEST_NAME = "android-version.json"
APK_MIME = "application/vnd.android.package-archive"
GITHUB_API_VERSION = "2022-11-28"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_download_windows: dict[str, dict[str, float | int]] = defaultdict(lambda: {"count": 0, "reset_time": 0.0})
_last_download_prune = 0.0


@dataclass(frozen=True)
class AndroidReleaseCache:
    release_dir: Path
    manifest_path: Path
    apk_path: Path


class ReleaseSyncError(RuntimeError):
    """Raised when the GitHub release cache cannot be refreshed."""


def data_dir() -> Path:
    return Path(os.getenv("LAWVER_DATA_DIR") or Path.cwd() / "data")


def release_cache() -> AndroidReleaseCache:
    release_dir = Path(os.getenv("LAWVER_RELEASE_DIR") or data_dir() / "releases" / "android").resolve()
    return AndroidReleaseCache(
        release_dir=release_dir,
        manifest_path=release_dir / MANIFEST_NAME,
        apk_path=release_dir / "Lawver.apk",
    )


def sync_enabled() -> bool:
    return os.getenv("LAWVER_RELEASE_SYNC_ON_STARTUP", "1").strip().lower() not in {"0", "false", "no", "off"}


def github_repo() -> str:
    return os.getenv("LAWVER_RELEASE_REPO", "Hill-1024/Lawyance").strip() or "Hill-1024/Lawyance"


def github_timeout() -> float:
    return float(os.getenv("LAWVER_RELEASE_SYNC_TIMEOUT", "20"))


def public_base_url(request: Request | None = None) -> str:
    configured = os.getenv("LAWVER_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    if request is not None:
        return str(request.base_url).rstrip("/")
    return "https://law.mutsumi.moe"


def apk_download_rpm() -> int:
    try:
        return max(int(os.getenv("LAWVER_APK_DOWNLOAD_RPM", "6")), 1)
    except ValueError:
        return 6


def apk_filename(manifest: dict[str, Any]) -> str:
    version_name = str(manifest.get("versionName") or "latest").strip() or "latest"
    return f"Lawver-{version_name}.apk"


def _headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("LAWVER_GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "Lawver-Release-Sync",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _download_headers() -> dict[str, str]:
    headers = {"User-Agent": "Lawver-Release-Sync"}
    token = os.getenv("GITHUB_TOKEN") or os.getenv("LAWVER_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _asset_by_name(assets: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for asset in assets:
        if asset.get("name") == name:
            return asset
    return None


def _asset_by_apk_name(assets: list[dict[str, Any]], preferred_name: str | None) -> dict[str, Any] | None:
    if preferred_name:
        match = _asset_by_name(assets, preferred_name)
        if match:
            return match
    apk_assets = [asset for asset in assets if str(asset.get("name") or "").lower().endswith(".apk")]
    return apk_assets[0] if apk_assets else None


def _read_response_text(response: requests.Response) -> str:
    response.raise_for_status()
    return response.text


def _download_text(url: str, timeout: float) -> str:
    response = requests.get(url, headers=_download_headers(), timeout=timeout)
    return _read_response_text(response)


def _download_file(url: str, target: Path, timeout: float) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with requests.get(url, headers=_download_headers(), timeout=timeout, stream=True) as response:
        response.raise_for_status()
        with open(target, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                digest.update(chunk)
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
    return size, digest.hexdigest()


def _validate_manifest(raw: dict[str, Any], published_at: str | None = None) -> dict[str, Any]:
    manifest = dict(raw)
    if manifest.get("platform") != ANDROID_PLATFORM:
        raise ReleaseSyncError("android-version.json platform must be android")
    if manifest.get("packageName") != ANDROID_PACKAGE_NAME:
        raise ReleaseSyncError(f"android-version.json packageName must be {ANDROID_PACKAGE_NAME}")

    version_code = manifest.get("versionCode")
    if not isinstance(version_code, int) or version_code <= 0:
        raise ReleaseSyncError("android-version.json versionCode must be a positive integer")

    version_name = manifest.get("versionName")
    if not isinstance(version_name, str) or not version_name.strip():
        raise ReleaseSyncError("android-version.json versionName must be a non-empty string")

    sha256 = manifest.get("sha256")
    if not isinstance(sha256, str) or not SHA256_RE.match(sha256):
        raise ReleaseSyncError("android-version.json sha256 must be a hex SHA-256 digest")

    size = manifest.get("size")
    if not isinstance(size, int) or size <= 0:
        raise ReleaseSyncError("android-version.json size must be a positive integer")

    manifest["publishedAt"] = str(manifest.get("publishedAt") or published_at or "")
    return manifest


def _preferred_apk_asset_name(manifest: dict[str, Any]) -> str | None:
    apk_url = str(manifest.get("apkUrl") or "")
    if not apk_url:
        return apk_filename(manifest)
    path = urlparse(apk_url).path
    return Path(path).name or apk_filename(manifest)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def sync_latest_release() -> dict[str, Any]:
    cache = release_cache()
    cache.release_dir.mkdir(parents=True, exist_ok=True)
    timeout = github_timeout()

    api_url = f"https://api.github.com/repos/{github_repo()}/releases/latest"
    release_response = requests.get(api_url, headers=_headers(), timeout=timeout)
    release_response.raise_for_status()
    release = release_response.json()
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseSyncError("GitHub release response did not include assets")

    manifest_asset = _asset_by_name(assets, MANIFEST_NAME)
    if not manifest_asset or not manifest_asset.get("browser_download_url"):
        raise ReleaseSyncError(f"GitHub release does not contain {MANIFEST_NAME}")

    manifest_text = _download_text(str(manifest_asset["browser_download_url"]), timeout)
    try:
        manifest = _validate_manifest(json.loads(manifest_text), release.get("published_at"))
    except json.JSONDecodeError as exc:
        raise ReleaseSyncError("android-version.json is not valid JSON") from exc

    apk_asset = _asset_by_apk_name(assets, _preferred_apk_asset_name(manifest))
    if not apk_asset or not apk_asset.get("browser_download_url"):
        raise ReleaseSyncError("GitHub release does not contain an APK asset")

    tmp_apk = cache.release_dir / f".{cache.apk_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        size, sha256 = _download_file(str(apk_asset["browser_download_url"]), tmp_apk, timeout)
        if size != manifest["size"]:
            raise ReleaseSyncError(f"APK size mismatch: expected {manifest['size']}, got {size}")
        if sha256.lower() != str(manifest["sha256"]).lower():
            raise ReleaseSyncError("APK sha256 mismatch")

        manifest["sha256"] = sha256.lower()
        manifest["size"] = size
        os.replace(tmp_apk, cache.apk_path)
        _atomic_write_json(cache.manifest_path, manifest)
    finally:
        try:
            if tmp_apk.exists():
                tmp_apk.unlink()
        except OSError:
            pass

    return {"status": "synced", "versionCode": manifest["versionCode"], "versionName": manifest["versionName"]}


def cached_manifest(request: Request | None = None) -> dict[str, Any] | None:
    cache = release_cache()
    if not cache.manifest_path.exists() or not cache.apk_path.exists():
        return None
    try:
        with open(cache.manifest_path, "r", encoding="utf-8") as f:
            manifest = _validate_manifest(json.load(f))
    except Exception:
        return None
    manifest["apkUrl"] = f"{public_base_url(request)}/api/releases/android/apk"
    return manifest


def cached_apk_path() -> Path | None:
    cache = release_cache()
    if not cache.apk_path.exists() or not cache.manifest_path.exists():
        return None
    return cache.apk_path


def consume_apk_download_slot(request: Request) -> bool:
    global _last_download_prune
    now = time.time()
    client_ip = client_ip_for_request(request)
    if now - _last_download_prune > 60:
        stale_ips = [ip for ip, data in _download_windows.items() if now > float(data["reset_time"])]
        for ip in stale_ips:
            del _download_windows[ip]
        _last_download_prune = now

    window = _download_windows[client_ip]
    if now > float(window["reset_time"]):
        window["count"] = 1
        window["reset_time"] = now + 60
        return True

    window["count"] = int(window["count"]) + 1
    return int(window["count"]) <= apk_download_rpm()


def reset_download_rate_limits() -> None:
    _download_windows.clear()


async def prepare_on_startup(app: FastAPI) -> None:
    if not sync_enabled():
        app.state.android_release_status = {"status": "disabled"}
        return

    try:
        status = await asyncio.to_thread(sync_latest_release)
    except Exception as exc:
        status = {
            "status": "cache" if cached_manifest() else "unavailable",
            "error": str(exc),
        }
    app.state.android_release_status = status
