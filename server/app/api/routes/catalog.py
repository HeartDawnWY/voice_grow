"""
分类/艺术家/标签 公开 API 路由
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Depends

from ...models.schemas import (
    CategoryListResponse, ArtistListResponse, TagListResponse,
)
from ...models.response import ErrorCode, BusinessException, success_response
from ..deps import get_content_service
from ...services.content_service import ContentService
from . import parse_content_type, parse_artist_type, parse_tag_type

router = APIRouter()
logger = logging.getLogger(__name__)


# ========== 分类 API ==========

@router.get("/api/v1/categories", response_model=CategoryListResponse)
async def get_categories(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取分类树"""
    content_type = parse_content_type(type)
    categories = await content_service.get_category_tree(content_type)
    return CategoryListResponse(categories=categories)


@router.get("/api/v1/contents/categories", response_model=CategoryListResponse)
async def get_categories_compat(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取分类树 (兼容路径)"""
    content_type = parse_content_type(type)
    categories = await content_service.get_category_tree(content_type)
    return CategoryListResponse(categories=categories)


@router.get("/api/categories/{category_id}")
async def get_category(
    category_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """获取单个分类详情"""
    category = await content_service.get_category_by_id(category_id)

    if not category:
        raise BusinessException(ErrorCode.CATEGORY_NOT_FOUND, "Category not found")

    return success_response(data=category)


@router.get("/api/categories/{category_id}/children")
async def get_category_children(
    category_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """获取分类的子分类"""
    children = await content_service.get_category_children(category_id)
    return success_response(data={"children": children})


# ========== 艺术家 API ==========

@router.get("/api/v1/artists", response_model=ArtistListResponse)
async def list_artists(
    type: Optional[str] = Query(None, description="艺术家类型: narrator, singer, composer, author"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取艺术家列表"""
    artist_type = parse_artist_type(type)

    result = await content_service.list_artists(
        artist_type=artist_type,
        keyword=keyword,
        page=page,
        page_size=page_size
    )
    return ArtistListResponse(**result)


@router.get("/api/artists/{artist_id}")
async def get_artist(
    artist_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """获取艺术家详情"""
    artist = await content_service.get_artist_by_id(artist_id)

    if not artist:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Artist not found")

    return success_response(data=artist)


@router.get("/api/artists/{artist_id}/contents")
async def get_artist_contents(
    artist_id: int,
    type: Optional[str] = Query(None, description="内容类型: story, music"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取艺术家的内容列表"""
    content_type = parse_content_type(type)

    result = await content_service.get_contents_by_artist(
        artist_id=artist_id,
        content_type=content_type,
        page=page,
        page_size=page_size
    )
    return success_response(data=result)


# ========== 标签 API ==========

@router.get("/api/v1/tags", response_model=TagListResponse)
async def list_tags(
    type: Optional[str] = Query(None, description="标签类型: theme, mood, age, scene"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取标签列表"""
    tag_type = parse_tag_type(type)
    tags = await content_service.list_tags(tag_type)
    return TagListResponse(tags=tags)


@router.get("/api/v1/tags/{tag_id}")
async def get_tag(
    tag_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """获取标签详情"""
    tag = await content_service.get_tag_by_id(tag_id)

    if not tag:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Tag not found")

    return success_response(data=tag)


@router.get("/api/tags/{tag_id}/contents")
async def get_tag_contents(
    tag_id: int,
    type: Optional[str] = Query(None, description="内容类型: story, music"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取标签下的内容列表"""
    content_type = parse_content_type(type)

    result = await content_service.get_contents_by_tag(
        tag_id=tag_id,
        content_type=content_type,
        page=page,
        page_size=page_size
    )
    return success_response(data=result)
