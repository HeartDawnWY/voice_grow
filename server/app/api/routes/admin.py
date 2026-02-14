"""
管理后台 API 路由

包含全部 Admin CRUD 操作
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Depends, Request

from ...models.schemas import (
    ContentCreateRequest, ContentUpdateRequest,
    WordCreateRequest, WordUpdateRequest,
    CategoryCreateRequest, CategoryUpdateRequest,
    ArtistCreateRequest, ArtistUpdateRequest,
    TagCreateRequest, TagUpdateRequest,
)
from ...models.response import ErrorCode, BusinessException, success_response
from ..deps import get_content_service
from ...services.content_service import ContentService
from . import parse_content_type, parse_artist_type, parse_tag_type

router = APIRouter()
logger = logging.getLogger(__name__)


# ========== Admin Content CRUD API ==========

@router.get("/api/v1/admin/contents")
async def admin_list_contents(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    category_id: Optional[int] = Query(None, description="分类 ID"),
    artist_id: Optional[int] = Query(None, description="艺术家 ID"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    is_active: Optional[bool] = Query(None, description="是否激活"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取内容列表 (管理后台)"""
    content_type = parse_content_type(type)

    result = await content_service.list_contents(
        content_type=content_type,
        category_id=category_id,
        artist_id=artist_id,
        keyword=keyword,
        is_active=is_active,
        page=page,
        page_size=page_size
    )

    return success_response(data=result)


@router.post("/api/v1/admin/contents")
async def admin_create_content(
    request: ContentCreateRequest,
    http_request: Request,
    content_service: ContentService = Depends(get_content_service)
):
    """创建内容 (管理后台)"""
    content_type = parse_content_type(request.type, required=True)

    content = await content_service.create_content(
        content_type=content_type,
        category_id=request.category_id,
        title=request.title,
        minio_path=request.minio_path,
        title_pinyin=request.title_pinyin,
        subtitle=request.subtitle,
        description=request.description,
        cover_path=request.cover_path,
        duration=request.duration,
        age_min=request.age_min,
        age_max=request.age_max,
        artist_ids=request.artist_ids,
        tag_ids=request.tag_ids
    )

    return success_response(data=content)


@router.get("/api/v1/admin/contents/{content_id}")
async def admin_get_content(
    content_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """获取单个内容详情 (管理后台)"""
    content = await content_service.get_content_by_id(content_id, include_inactive=True, admin_view=True)

    if not content:
        raise BusinessException(ErrorCode.CONTENT_NOT_FOUND, "Content not found")

    return success_response(data=content)


@router.put("/api/v1/admin/contents/{content_id}")
async def admin_update_content(
    content_id: int,
    request: ContentUpdateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """更新内容 (管理后台)"""
    update_data = request.model_dump(exclude_none=True)

    if not update_data:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "No fields to update")

    content = await content_service.update_content(content_id, update_data)

    if not content:
        raise BusinessException(ErrorCode.CONTENT_NOT_FOUND, "Content not found")

    return success_response(data=content)


@router.delete("/api/v1/admin/contents/{content_id}")
async def admin_delete_content(
    content_id: int,
    hard: bool = Query(False, description="是否物理删除"),
    content_service: ContentService = Depends(get_content_service)
):
    """删除内容 (管理后台)"""
    success = await content_service.delete_content(content_id, hard=hard)

    if not success:
        raise BusinessException(ErrorCode.CONTENT_NOT_FOUND, "Content not found")

    return success_response(message="Content deleted")


# ========== Admin File Upload API ==========

@router.post("/api/v1/admin/upload/presigned-url")
async def admin_get_upload_url(
    http_request: Request,
    filename: str = Query(..., description="文件名"),
    folder: str = Query("stories", description="文件夹: stories, music, english, covers"),
):
    """获取预签名上传 URL"""
    import re
    import uuid
    from datetime import datetime

    ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
    FOLDER_EXTENSIONS = {
        "stories": ALLOWED_AUDIO_EXTENSIONS,
        "music": ALLOWED_AUDIO_EXTENSIONS,
        "english": ALLOWED_AUDIO_EXTENSIONS,
        "covers": ALLOWED_IMAGE_EXTENSIONS,
    }

    if folder not in FOLDER_EXTENSIONS:
        raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid folder: {folder}")

    ext = ""
    if "." in filename:
        raw_ext = filename.rsplit(".", 1)[-1].lower()
        ext = re.sub(r'[^a-z0-9]', '', raw_ext)[:10]

    allowed_exts = FOLDER_EXTENSIONS[folder]
    if not ext or ext not in allowed_exts:
        raise BusinessException(
            ErrorCode.INVALID_PARAMS,
            f"File type '{ext}' not allowed for folder '{folder}'. Allowed: {', '.join(sorted(allowed_exts))}"
        )

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    object_name = f"{folder}/{timestamp}_{unique_id}.{ext}"

    minio_service = http_request.app.state.minio_service
    upload_url = await minio_service.presigned_put_url(object_name)

    return success_response(data={
        "upload_url": upload_url,
        "object_name": object_name,
    })


# ========== Admin English Word CRUD API ==========

@router.get("/api/v1/admin/words")
async def admin_list_words(
    level: Optional[str] = Query(None, description="级别: basic, elementary, intermediate"),
    category_id: Optional[int] = Query(None, description="分类 ID"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取单词列表 (管理后台)"""
    result = await content_service.list_words(
        level=level,
        category_id=category_id,
        keyword=keyword,
        page=page,
        page_size=page_size
    )

    return success_response(data=result)


@router.post("/api/v1/admin/words")
async def admin_create_word(
    request: WordCreateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """创建单词 (管理后台)"""
    word = await content_service.create_word(
        word=request.word,
        phonetic_us=request.phonetic_us,
        phonetic_uk=request.phonetic_uk,
        translation=request.translation,
        audio_us_path=request.audio_us_path,
        audio_uk_path=request.audio_uk_path,
        level=request.level,
        category_id=request.category_id,
        example_sentence=request.example_sentence,
        example_translation=request.example_translation
    )

    return success_response(data=word)


@router.get("/api/v1/admin/words/{word_id}")
async def admin_get_word(
    word_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """获取单个单词详情 (管理后台)"""
    word = await content_service.get_word_by_id(word_id)

    if not word:
        raise BusinessException(ErrorCode.WORD_NOT_FOUND, "Word not found")

    return success_response(data=word)


@router.put("/api/v1/admin/words/{word_id}")
async def admin_update_word(
    word_id: int,
    request: WordUpdateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """更新单词 (管理后台)"""
    update_data = request.model_dump(exclude_none=True)

    if not update_data:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "No fields to update")

    word = await content_service.update_word(word_id, update_data)

    if not word:
        raise BusinessException(ErrorCode.WORD_NOT_FOUND, "Word not found")

    return success_response(data=word)


@router.delete("/api/v1/admin/words/{word_id}")
async def admin_delete_word(
    word_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """删除单词 (管理后台)"""
    success = await content_service.delete_word(word_id)

    if not success:
        raise BusinessException(ErrorCode.WORD_NOT_FOUND, "Word not found")

    return success_response(message="Word deleted")


# ========== Admin List API (includes inactive) ==========

@router.get("/api/v1/admin/categories")
async def admin_list_categories(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取分类列表 (管理后台，含停用)"""
    content_type = parse_content_type(type)
    categories = await content_service.list_categories_admin(content_type)
    return success_response(data={"categories": categories})


@router.get("/api/v1/admin/tags")
async def admin_list_tags(
    type: Optional[str] = Query(None, description="标签类型: theme, mood, age, scene, feature"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取标签列表 (管理后台，含停用)"""
    tag_type = parse_tag_type(type)
    tags = await content_service.list_tags_admin(tag_type)
    return success_response(data={"tags": tags})


@router.get("/api/v1/admin/artists")
async def admin_list_artists(
    type: Optional[str] = Query(None, description="艺术家类型: narrator, singer, composer, author, band"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取艺术家列表 (管理后台，含停用)"""
    artist_type = parse_artist_type(type)

    result = await content_service.list_artists_admin(
        artist_type=artist_type,
        keyword=keyword,
        page=page,
        page_size=page_size
    )
    return success_response(data=result)


# ========== Admin Category CRUD API ==========

@router.post("/api/v1/admin/categories")
async def admin_create_category(
    request: CategoryCreateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """创建分类 (管理后台)"""
    content_type = parse_content_type(request.type, required=True)

    category = await content_service.create_category(
        name=request.name,
        content_type=content_type,
        parent_id=request.parent_id,
        description=request.description,
        icon=request.icon,
        sort_order=request.sort_order
    )

    return success_response(data=category)


@router.put("/api/v1/admin/categories/{category_id}")
async def admin_update_category(
    category_id: int,
    request: CategoryUpdateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """更新分类 (管理后台)"""
    update_data = request.model_dump(exclude_none=True)

    if not update_data:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "No fields to update")

    category = await content_service.update_category(category_id, update_data)

    if not category:
        raise BusinessException(ErrorCode.CATEGORY_NOT_FOUND, "Category not found")

    return success_response(data=category)


@router.delete("/api/v1/admin/categories/{category_id}")
async def admin_delete_category(
    category_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """删除分类 (管理后台)"""
    success = await content_service.delete_category(category_id)

    if not success:
        raise BusinessException(ErrorCode.CATEGORY_NOT_FOUND, "Category not found")

    return success_response(message="Category deleted")


# ========== Admin Artist CRUD API ==========

@router.post("/api/v1/admin/artists")
async def admin_create_artist(
    request: ArtistCreateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """创建艺术家 (管理后台)"""
    artist_type = parse_artist_type(request.type, required=True)

    artist = await content_service.create_artist(
        name=request.name,
        artist_type=artist_type,
        avatar=request.avatar,
        description=request.description
    )

    return success_response(data=artist)


@router.put("/api/v1/admin/artists/{artist_id}")
async def admin_update_artist(
    artist_id: int,
    request: ArtistUpdateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """更新艺术家 (管理后台)"""
    update_data = request.model_dump(exclude_none=True)

    if not update_data:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "No fields to update")

    artist = await content_service.update_artist(artist_id, update_data)

    if not artist:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Artist not found")

    return success_response(data=artist)


@router.delete("/api/v1/admin/artists/{artist_id}")
async def admin_delete_artist(
    artist_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """删除艺术家 (管理后台)"""
    success = await content_service.delete_artist(artist_id)

    if not success:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Artist not found")

    return success_response(message="Artist deleted")


# ========== Admin Tag CRUD API ==========

@router.post("/api/v1/admin/tags")
async def admin_create_tag(
    request: TagCreateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """创建标签 (管理后台)"""
    tag_type = parse_tag_type(request.type, required=True)

    tag = await content_service.create_tag(
        name=request.name,
        tag_type=tag_type,
        color=request.color,
        sort_order=request.sort_order
    )

    return success_response(data=tag)


@router.put("/api/v1/admin/tags/{tag_id}")
async def admin_update_tag(
    tag_id: int,
    request: TagUpdateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """更新标签 (管理后台)"""
    update_data = request.model_dump(exclude_none=True)

    if not update_data:
        raise BusinessException(ErrorCode.INVALID_PARAMS, "No fields to update")

    tag = await content_service.update_tag(tag_id, update_data)

    if not tag:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Tag not found")

    return success_response(data=tag)


@router.delete("/api/v1/admin/tags/{tag_id}")
async def admin_delete_tag(
    tag_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """删除标签 (管理后台)"""
    success = await content_service.delete_tag(tag_id)

    if not success:
        raise BusinessException(ErrorCode.RESOURCE_NOT_FOUND, "Tag not found")

    return success_response(message="Tag deleted")
