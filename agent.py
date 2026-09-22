"""
模块描述：仓库根启动契约。真实应用代码在 backend/，此处只负责路径与入口转发。

保留：
- `uvicorn agent:app` / `python agent.py`
- 现有部署与本地开发习惯
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent / "backend"
_backend = str(_BACKEND_DIR)
if _backend not in sys.path:
    sys.path.insert(0, _backend)

import uvicorn

from app_config import PORT
from app_factory import create_app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", str(PORT)))
    workers = max(int(os.getenv("UVICORN_WORKERS", "1")), 1)
    uvicorn.run("agent:app", host="0.0.0.0", port=port, workers=workers)
