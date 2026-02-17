"""
内容下载 API 路由
"""

import logging

from fastapi import APIRouter, Depends

from ...models.schemas import YouTubeDownloadRequest, SearchRequest, BatchDownloadRequest
from ...models.response import ErrorCode, BusinessException, success_response
from ..deps import get_download_service
from ...services.download_service import DownloadService

router = APIRouter()
logger = logging.getLogger(__name__)


# ========== 原有端点 (保持兼容) ==========

@router.post("/api/v1/admin/youtube/download")
async def start_download(
    request: YouTubeDownloadRequest,
    download_service: DownloadService = Depends(get_download_service),
):
    """创建下载任务（URL 下载）"""
    task = download_service.start_download(
        url=request.url,
        content_type=request.content_type,
        category_id=request.category_id,
        artist_name=request.artist_name,
        artist_type=request.artist_type,
        tag_ids=request.tag_ids,
        age_min=request.age_min,
        age_max=request.age_max,
    )
    return success_response(data=task.to_dict())


@router.get("/api/v1/admin/youtube/tasks")
async def list_tasks(
    download_service: DownloadService = Depends(get_download_service),
):
    """获取所有下载任务"""
    tasks = download_service.list_tasks()
    return success_response(data=tasks)


@router.get("/api/v1/admin/youtube/tasks/{task_id}")
async def get_task(
    task_id: str,
    download_service: DownloadService = Depends(get_download_service),
):
    """获取单个任务进度"""
    task = download_service.get_task(task_id)
    if not task:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Task not found")
    return success_response(data=task.to_dict())


@router.post("/api/v1/admin/youtube/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    download_service: DownloadService = Depends(get_download_service),
):
    """取消下载任务"""
    success = download_service.cancel_task(task_id)
    if not success:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "无法取消该任务")
    return success_response(message="Task cancelled")


# ========== 新增端点：搜索 + 批量下载 ==========

@router.post("/api/v1/admin/download/search")
async def search_content(
    request: SearchRequest,
    download_service: DownloadService = Depends(get_download_service),
):
    """多平台关键字搜索"""
    result = await download_service.search(
        keyword=request.keyword,
        platforms=request.platforms,
        content_type=request.content_type,
        max_results=request.max_results,
    )
    return success_response(data=result)


@router.post("/api/v1/admin/download/batch")
async def batch_download(
    request: BatchDownloadRequest,
    download_service: DownloadService = Depends(get_download_service),
):
    """批量下载选中项"""
    if not request.urls:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "至少选择一个内容")

    task = download_service.start_batch_download(
        urls=request.urls,
        content_type=request.content_type,
        category_id=request.category_id,
        artist_name=request.artist_name,
        artist_type=request.artist_type,
        tag_ids=request.tag_ids,
        age_min=request.age_min,
        age_max=request.age_max,
    )
    return success_response(data=task.to_dict())


@router.get("/api/v1/admin/download/platforms")
async def get_platforms(
    download_service: DownloadService = Depends(get_download_service),
):
    """获取可用搜索平台列表"""
    platforms = download_service.get_available_platforms()
    return success_response(data=platforms)
