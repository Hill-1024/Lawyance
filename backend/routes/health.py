"""
模块描述：进程级健康检查，供同机的分流核心探活。

免鉴权、不碰数据库：核心据此判断「功能页是否在线」，判定在线就把请求转进来，所以这里
只回答进程本身活着。数据库是否可用由具体接口自己报错，探活不该把它算成下线——
否则一次数据库抖动会让整个功能页被推进维护态。

这个路径在 app_security.should_record_usage_log 里被排除，不写访问日志。
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "lawver-app"}
