"""
HTTP REST API

提供内容管理、健康检查等 HTTP 接口
路由按域拆分到 routes/ 子包，此文件作为聚合入口
"""

from fastapi import APIRouter

from .routes.health import router as health_router
from .routes.content import router as content_router
from .routes.catalog import router as catalog_router
from .routes.device import router as device_router
from .routes.admin import router as admin_router

router = APIRouter()
router.include_router(health_router)
router.include_router(content_router)
router.include_router(catalog_router)
router.include_router(device_router)
router.include_router(admin_router)
