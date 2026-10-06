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
from workbench import api as workbench_api, worker as workbench_worker, migration as workbench_migration, backup as workbench_backup
from routes import (
    admin,
    announcements,
    auth,
    billing,
    court,
    health,
    releases,
    settings,
    spa,
    workspace,
)
from services import law_cache, release_sync, settings_service, workspace_cleanup
from services.app_security import security_and_logging_middleware


_logger = logging.getLogger("lawver.startup")


def _prepare_request_shielding() -> None:
    """启动时引导账号库、探测 Redis 并用有效会话预热布隆过滤器。"""
    # 账号库现在在云端：这里显式连一次，让「没配数据库」或「引导失败」
    # 在启动日志里就暴露，而不是拖到某个用户点登录。缺配置时不会中断启动。
    auth_service.ensure_auth_store_ready()
    if auth_service.auth_store_ready():
        _logger.info("云端账号库已就绪。")
    else:
        _logger.warning("云端账号库不可用：登录与工作台将不可使用，请检查 LAWVER_DATABASE_URL。")
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
    workspace_cleanup.start(app)
    workbench_worker.start(app)
    # 预热在事件循环外执行：读会话表与 Redis 建位图都不该阻塞首个请求。
    await asyncio.to_thread(_prepare_request_shielding)
    yield
    await workbench_worker.stop(app)
    await workspace_cleanup.stop(app)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    # 来源控制（CORS/Origin 校验）交由网关层处理，应用内不再注册 CORSMiddleware。

    # 1. 安全/日志中间件必须在路由前注册。
    app.middleware("http")(security_and_logging_middleware)

    # 2. API 路由顺序固定：health -> auth -> admin -> court -> releases -> workspace/upload/download。
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(billing.router)
    app.include_router(announcements.router)
    app.include_router(court.router)
    app.include_router(releases.router)
    app.include_router(settings.router)
    app.include_router(workspace.router)
    app.include_router(workbench_backup.router)
    app.include_router(workbench_migration.router)
    app.include_router(workbench_api.router)

    # 3. SPA catch-all 必须最后注册，避免吞掉 /api/*。
    app.include_router(spa.router)

    return app
