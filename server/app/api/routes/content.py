"""
内容公开 API 路由

包含内容列表/详情、随机故事/音乐、英语单词、搜索、播放历史
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Depends

from ...models.schemas import (
    ContentResponse, PaginatedContentResponse,
    WordResponse, SearchResultResponse,
)
from ...models.response import ErrorCode, BusinessException, success_response
from ..deps import get_content_service
from ...services.content_service import ContentService
from . import parse_content_type

router = APIRouter()
logger = logging.getLogger(__name__)


# ========== 内容 API ==========

@router.get("/api/v1/contents", response_model=PaginatedContentResponse)
async def list_contents(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    category_id: Optional[int] = Query(None, description="分类ID"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取内容列表"""
    content_type = parse_content_type(type)

    result = await content_service.list_contents(
        content_type=content_type,
        category_id=category_id,
        keyword=keyword,
        is_active=True,
        page=page,
        page_size=page_size
    )

    return PaginatedContentResponse(
        items=[
            ContentResponse(
                id=item["id"],
                type=item["type"],
                category=item.get("category_name", ""),
                title=item["title"],
                description=item.get("description"),
                play_url=item.get("play_url", ""),
                duration=item.get("duration"),
                tags=[t["name"] for t in item.get("tags", [])]
            )
            for item in result["items"]
        ],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
        total_pages=result["total_pages"]
    )


@router.get("/api/v1/contents/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """获取单个内容"""
    content = await content_service.get_content_by_id(content_id)

    if not content:
        raise BusinessException(ErrorCode.CONTENT_NOT_FOUND, "Content not found")

    return ContentResponse(
        id=content["id"],
        type=content["type"],
        category=content.get("category", ""),
        title=content["title"],
        description=content.get("description"),
        play_url=content["play_url"],
        duration=content.get("duration"),
        tags=content.get("tags", [])
    )


@router.get("/api/v1/stories/random", response_model=ContentResponse)
async def get_random_story(
    category: Optional[str] = Query(None, description="故事分类"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取随机故事"""
    content = await content_service.get_random_story(category)

    if not content:
        raise BusinessException(ErrorCode.CONTENT_NOT_FOUND, "No stories found")

    return ContentResponse(
        id=content["id"],
        type=content["type"],
        category=content.get("category", ""),
        title=content["title"],
        description=content.get("description"),
        play_url=content["play_url"],
        duration=content.get("duration"),
        tags=content.get("tags", [])
    )


@router.get("/api/v1/music/random", response_model=ContentResponse)
async def get_random_music(
    category: Optional[str] = Query(None, description="音乐分类"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取随机音乐"""
    content = await content_service.get_random_music(category)

    if not content:
        raise BusinessException(ErrorCode.CONTENT_NOT_FOUND, "No music found")

    return ContentResponse(
        id=content["id"],
        type=content["type"],
        category=content.get("category", ""),
        title=content["title"],
        description=content.get("description"),
        play_url=content["play_url"],
        duration=content.get("duration"),
        tags=content.get("tags", [])
    )


# ========== 英语学习 API ==========

@router.get("/api/v1/english/word/{word}", response_model=WordResponse)
async def get_word(
    word: str,
    content_service: ContentService = Depends(get_content_service)
):
    """获取单词信息"""
    word_info = await content_service.get_word(word)

    if not word_info:
        raise BusinessException(ErrorCode.WORD_NOT_FOUND, "Word not found")

    return WordResponse(
        word=word_info["word"],
        phonetic_us=word_info.get("phonetic_us"),
        phonetic_uk=word_info.get("phonetic_uk"),
        translation=word_info["translation"],
        audio_us_url=word_info.get("audio_us_url"),
        audio_uk_url=word_info.get("audio_uk_url"),
        example=word_info.get("example")
    )


@router.get("/api/v1/english/random", response_model=WordResponse)
async def get_random_word(
    level: Optional[str] = Query(None, description="级别: basic, elementary, intermediate"),
    category: Optional[str] = Query(None, description="分类: animal, food, color"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取随机单词"""
    word_info = await content_service.get_random_word(level, category)

    if not word_info:
        raise BusinessException(ErrorCode.WORD_NOT_FOUND, "No words found")

    return WordResponse(
        word=word_info["word"],
        phonetic_us=word_info.get("phonetic_us"),
        phonetic_uk=word_info.get("phonetic_uk"),
        translation=word_info["translation"],
        audio_us_url=word_info.get("audio_us_url"),
        audio_uk_url=word_info.get("audio_uk_url"),
        example=word_info.get("example")
    )


# ========== 搜索 API ==========

@router.get("/api/v1/search", response_model=SearchResultResponse)
async def smart_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """智能搜索"""
    content_type = parse_content_type(type)

    results = await content_service.smart_search(q, content_type, limit)
    return SearchResultResponse(results=results, total=len(results))


# ========== 播放历史 API ==========

@router.get("/api/devices/{device_id}/history")
async def get_device_history(
    device_id: str,
    limit: int = Query(10, ge=1, le=50),
    content_service: ContentService = Depends(get_content_service)
):
    """获取设备播放历史"""
    history = await content_service.get_recent_history(device_id, limit)
    return success_response(data={"history": history})
