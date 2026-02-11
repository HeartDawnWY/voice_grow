"""
健康检查路由
"""

import logging

from fastapi import APIRouter, Request
from sqlalchemy import text

from ...models.schemas import HealthResponse
from ...models.response import success_response

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查接口"""
    return HealthResponse(
        status="ok",
        version="0.1.0"
    )


@router.get("/api/v1/health/detail")
async def health_detail(request: Request):
    """详细健康检查 (各组件状态)"""
    components = {
        "database": {"status": "unknown"},
        "minio": {"status": "unknown"},
        "redis": {"status": "unknown"},
    }

    # 检查数据库
    try:
        engine = request.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            components["database"] = {"status": "healthy"}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "error": str(e)}

    # 检查 MinIO
    try:
        minio = request.app.state.minio_service
        components["minio"] = {"status": "healthy"}
    except Exception as e:
        components["minio"] = {"status": "unhealthy", "error": str(e)}

    # 检查 Redis
    if hasattr(request.app.state, 'redis_service'):
        try:
            redis_service = request.app.state.redis_service
            health_result = await redis_service.health_check()
            components["redis"] = health_result
        except Exception as e:
            components["redis"] = {"status": "unhealthy", "error": str(e)}

    all_healthy = all(
        c.get("status") in ("healthy", "unknown") for c in components.values()
    )

    return success_response(data={
        "status": "healthy" if all_healthy else "degraded",
        "version": "0.1.0",
        "components": components,
    })


@router.get("/ready")
async def readiness_check(request: Request):
    """就绪检查接口"""
    checks = {
        "database": False,
        "minio": False,
        "redis": False
    }

    try:
        engine = request.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            checks["database"] = True
    except Exception as e:
        logger.error(f"数据库检查失败: {e}")

    try:
        minio = request.app.state.minio_service
        checks["minio"] = True
    except Exception as e:
        logger.error(f"MinIO 检查失败: {e}")

    if hasattr(request.app.state, 'redis_service'):
        try:
            redis_service = request.app.state.redis_service
            health_result = await redis_service.health_check()
            checks["redis"] = health_result.get("status") == "healthy"
        except Exception as e:
            logger.error(f"Redis 检查失败: {e}")
    elif hasattr(request.app.state, 'session_service'):
        try:
            session_service = request.app.state.session_service
            checks["redis"] = await session_service.ping()
        except Exception as e:
            logger.error(f"Redis 检查失败: {e}")
    else:
        checks["redis"] = True

    all_ready = all(checks.values())

    return success_response(data={
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
    })
