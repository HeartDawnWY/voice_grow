"""
YouTube 下载 API 路由
"""

import logging

from fastapi import APIRouter, Depends

from ...models.schemas import YouTubeDownloadRequest
from ...models.response import ErrorCode, BusinessException, success_response
from ..deps import get_youtube_service
from ...services.youtube_service import YouTubeService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/v1/admin/youtube/download")
async def start_download(
    request: YouTubeDownloadRequest,
    youtube_service: YouTubeService = Depends(get_youtube_service),
):
    """创建 YouTube 下载任务"""
    task = youtube_service.start_download(
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
    youtube_service: YouTubeService = Depends(get_youtube_service),
):
    """获取所有下载任务"""
    tasks = youtube_service.list_tasks()
    return success_response(data=tasks)


@router.get("/api/v1/admin/youtube/tasks/{task_id}")
async def get_task(
    task_id: str,
    youtube_service: YouTubeService = Depends(get_youtube_service),
):
    """获取单个任务进度"""
    task = youtube_service.get_task(task_id)
    if not task:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Task not found")
    return success_response(data=task.to_dict())


@router.post("/api/v1/admin/youtube/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    youtube_service: YouTubeService = Depends(get_youtube_service),
):
    """取消下载任务"""
    success = youtube_service.cancel_task(task_id)
    if not success:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "无法取消该任务")
    return success_response(message="Task cancelled")
