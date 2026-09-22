"""
模块描述：后端启动期本地法库缓存准备服务。

四套库各自独立，互不并入对方的 SQLite：

- 中国法主库
- 大陆法系（印尼 / 泰国 / 越南）
- 伊斯兰法系（马来西亚 / 印尼专题）
- 普通法系（缅甸 / 新加坡）
"""

import asyncio

from fastapi import FastAPI

from mcps import (
    ensure_civil_law_database_ready,
    ensure_common_law_database_ready,
    ensure_islamic_database_ready,
    ensure_law_database_ready,
)


async def _prepare(loader) -> dict:
    """单套法域库失败只记录原因，不挡住中国法主库和服务启动。"""
    try:
        status = await asyncio.to_thread(loader)
        return status if isinstance(status, dict) else {"mode": "unknown", "status": status}
    except Exception as exc:
        return {"mode": "failed", "error": f"{type(exc).__name__}: {exc}"}


async def prepare_on_startup(app: FastAPI) -> None:
    status = await asyncio.to_thread(ensure_law_database_ready)
    app.state.law_cache_status = status
    mode = status.get("mode", "unknown")
    file_count = status.get("file_count", 0)
    print(f"[法库] 启动缓存准备完成: mode={mode}, files={file_count}")

    for label, attr, loader in (
        ("大陆法系", "civil_law_cache_status", ensure_civil_law_database_ready),
        ("伊斯兰法系", "islamic_law_cache_status", ensure_islamic_database_ready),
        ("普通法系", "common_law_cache_status", ensure_common_law_database_ready),
    ):
        jurisdiction_status = await _prepare(loader)
        setattr(app.state, attr, jurisdiction_status)
        if jurisdiction_status.get("mode") == "failed":
            print(f"[法系库] {label}缓存准备失败: {jurisdiction_status.get('error')}")
        else:
            print(f"[法系库] {label}缓存准备完成: mode={jurisdiction_status.get('mode', 'unknown')}")
