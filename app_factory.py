"""
模块描述：FastAPI 应用工厂，集中注册中间件、路由和生命周期任务。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import admin, auth, chat, court, spa, workspace
from services import law_cache, workspace_cleanup
from services.app_security import ALLOWED_ORIGINS, LOCAL_ORIGIN_RE, security_and_logging_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await law_cache.prepare_on_startup(app)
    workspace_cleanup.start(app)
    yield
    await workspace_cleanup.stop(app)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_origin_regex=LOCAL_ORIGIN_RE.pattern,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 1. 安全/日志中间件必须在路由前注册。
    app.middleware("http")(security_and_logging_middleware)

    # 2. API 路由顺序固定：auth -> admin -> chat -> court -> workspace/upload/download。
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(chat.router)
    app.include_router(court.router)
    app.include_router(workspace.router)

    # 3. SPA catch-all 必须最后注册，避免吞掉 /api/*。
    app.include_router(spa.router)

    return app
