"""
模块描述：后端启动期本地法库缓存准备服务。
"""

import asyncio

from fastapi import FastAPI

from RAG.law_data_search import ensure_law_database_ready


async def prepare_on_startup(app: FastAPI) -> None:
    status = await asyncio.to_thread(ensure_law_database_ready)
    app.state.law_cache_status = status
    mode = status.get("mode", "unknown")
    file_count = status.get("file_count", 0)
    print(f"[法库] 启动缓存准备完成: mode={mode}, files={file_count}")
