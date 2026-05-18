"""
模块描述：FastAPI 应用入口，保留 agent:app 与 python agent.py 启动契约。
"""

import os

import uvicorn

from app_factory import create_app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    workers = max(int(os.getenv("UVICORN_WORKERS", "1")), 1)
    uvicorn.run("agent:app", host="0.0.0.0", port=port, workers=workers)
