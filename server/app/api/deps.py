"""
依赖注入

FastAPI 依赖注入函数，从 http.py 提取
"""

from fastapi import Request

from ..services.content_service import ContentService
from ..services.redis_service import RedisService
from ..services.minio_service import MinIOService
from ..services.session_service import SessionService


async def get_content_service(request: Request) -> ContentService:
    """获取内容服务实例"""
    return request.app.state.content_service


async def get_redis_service(request: Request) -> RedisService:
    """获取 Redis 服务实例"""
    return request.app.state.redis_service


async def get_session_factory(request: Request):
    """获取数据库会话工厂"""
    return request.app.state.session_factory


async def get_minio_service(request: Request) -> MinIOService:
    """获取 MinIO 服务实例"""
    return request.app.state.minio_service


async def get_session_service(request: Request) -> SessionService:
    """获取会话服务实例"""
    return request.app.state.session_service
