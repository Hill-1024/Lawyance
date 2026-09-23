"""
模块描述：FastAPI 应用工厂，集中注册中间件、路由和生命周期任务。
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import auth as auth_service
from infra import redis_backend
from memory_system import reload_embedding_config
from routes import admin, auth, chat, court, releases, settings, spa, webdav, workspace
from services import law_cache, release_sync, settings_service, stream_buffer, workspace_cleanup
from services.app_security import security_and_logging_middleware


_logger = logging.getLogger("lawver.startup")


def _prepare_request_shielding() -> None:
    """启动时探测 Redis 并用有效会话预热布隆过滤器。"""
    redis_status = redis_backend.status()
    if redis_status["configured"]:
        _logger.info(
            "Redis 请求防护：available=%s prefix=%s",
            redis_status["available"],
            redis_status["prefix"],
        )
    added = auth_service.warm_session_bloom()
    _logger.info("会话布隆过滤器预热完成：%s 新置位（%s）", added, auth_service.bloom_status())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 管理后台保存的 provider 配置优先于 .env，启动时即同步到进程环境变量；
    # embedding 配置在 memory_system 导入期读取，同步后需显式重载才会生效。
    settings_service.apply_provider_env()
    reload_embedding_config()
    await law_cache.prepare_on_startup(app)
    await release_sync.prepare_on_startup(app)
    stream_buffer.start(app)
    workspace_cleanup.start(app)
    # 预热在事件循环外执行：读会话表与 Redis 建位图都不该阻塞首个请求。
    await asyncio.to_thread(_prepare_request_shielding)
    yield
    await stream_buffer.stop(app)
    await workspace_cleanup.stop(app)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # 来源控制（CORS/Origin 校验）交由网关层处理，应用内不再注册 CORSMiddleware。

    # 1. 安全/日志中间件必须在路由前注册。
    app.middleware("http")(security_and_logging_middleware)

    # 2. API 路由顺序固定：auth -> admin -> chat -> court -> releases -> workspace/upload/download。
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(chat.router)
    app.include_router(court.router)
    app.include_router(releases.router)
    app.include_router(settings.router)
    app.include_router(webdav.router)
    app.include_router(workspace.router)

    # 3. SPA catch-all 必须最后注册，避免吞掉 /api/*。
    app.include_router(spa.router)

    return app
