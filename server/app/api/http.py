"""
HTTP REST API

提供内容管理、健康检查等 HTTP 接口
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Depends, Request
from sqlalchemy import text

from ..models.database import ContentType, ArtistType, TagType
from ..models.schemas import (
    ContentCreateRequest, ContentUpdateRequest,
    WordCreateRequest, WordUpdateRequest,
    DeviceCommandRequest,
    HealthResponse, ContentResponse, ContentListResponse,
    WordResponse, CategoryResponse, CategoryListResponse,
    ArtistResponse, ArtistListResponse,
    TagResponse, TagListResponse,
    SearchResultResponse, PaginatedContentResponse,
    DeviceDetailResponse, HealthDetailResponse, PlaybackStatsResponse,
)
from ..models.response import (
    ErrorCode, BusinessException, success_response, error_response,
)
from .deps import get_content_service, get_redis_service
from ..services.content_service import ContentService
from ..services.redis_service import RedisService

router = APIRouter()
logger = logging.getLogger(__name__)


# ========== 健康检查 ==========

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
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)
        if not content_type:
            raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid content type: {type}")

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


# ========== 分类 API ==========

@router.get("/api/v1/categories", response_model=CategoryListResponse)
async def get_categories(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取分类树"""
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)
        if not content_type:
            raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid type: {type}")

    categories = await content_service.get_category_tree(content_type)
    return CategoryListResponse(categories=categories)


@router.get("/api/v1/contents/categories", response_model=CategoryListResponse)
async def get_categories_compat(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取分类树 (兼容路径)"""
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)
        if not content_type:
            raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid type: {type}")

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
    artist_type = None
    if type:
        type_mapping = {
            "narrator": ArtistType.NARRATOR,
            "singer": ArtistType.SINGER,
            "composer": ArtistType.COMPOSER,
            "author": ArtistType.AUTHOR,
            "band": ArtistType.BAND,
        }
        artist_type = type_mapping.get(type)
        if not artist_type:
            raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid artist type: {type}")

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
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)

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
    tag_type = None
    if type:
        type_mapping = {
            "theme": TagType.THEME,
            "mood": TagType.MOOD,
            "age": TagType.AGE,
            "scene": TagType.SCENE,
            "feature": TagType.FEATURE,
        }
        tag_type = type_mapping.get(type)
        if not tag_type:
            raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid tag type: {type}")

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
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)

    result = await content_service.get_contents_by_tag(
        tag_id=tag_id,
        content_type=content_type,
        page=page,
        page_size=page_size
    )
    return success_response(data=result)


# ========== 搜索 API ==========

@router.get("/api/v1/search", response_model=SearchResultResponse)
async def smart_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """智能搜索"""
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)
        if not content_type:
            raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid type: {type}")

    results = await content_service.smart_search(q, content_type, limit)
    return SearchResultResponse(results=results, total=len(results))


# ========== 设备管理 API ==========

@router.get("/api/v1/devices")
async def list_devices():
    """获取已连接的设备列表"""
    from .websocket import manager

    devices = []
    for device_id, conn in manager.connections.items():
        devices.append({
            "device_id": device_id,
            "state": conn.state.value,
            "playing_state": conn.playing_state.value,
        })

    return success_response(data={"devices": devices, "total": len(devices)})


@router.get("/api/v1/devices/{device_id}")
async def get_device_detail(device_id: str):
    """获取设备详情"""
    from .websocket import manager

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    data = {
        "device_id": device_id,
        "state": conn.state.value,
        "playing_state": conn.playing_state.value,
        "current_content": conn.current_content,
    }
    return success_response(data=data)


@router.post("/api/v1/devices/{device_id}/command")
async def device_command(
    device_id: str,
    body: DeviceCommandRequest,
    http_request: Request,
):
    """通用命令发送"""
    from .websocket import manager
    from ..models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    command = body.command
    params = body.params

    if command == "play_url":
        url = params.get("url", "")
        if not url:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Missing 'url' param")
        await manager.send_request(device_id, ProtocolRequest.play_url(url))
    elif command == "pause":
        await manager.send_request(device_id, ProtocolRequest.pause())
    elif command == "play":
        await manager.send_request(device_id, ProtocolRequest.play())
    elif command == "volume_up":
        await manager.send_request(device_id, ProtocolRequest.volume_up())
    elif command == "volume_down":
        await manager.send_request(device_id, ProtocolRequest.volume_down())
    elif command == "speak":
        text = params.get("text", "")
        if not text:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Missing 'text' param")
        tts_service = http_request.app.state.tts_service
        audio_url = await tts_service.synthesize_to_url(text)
        await manager.send_request(device_id, ProtocolRequest.play_url(audio_url))
        return success_response(data={"audio_url": audio_url})
    else:
        raise BusinessException(ErrorCode.INVALID_PARAMS, f"Unknown command: {command}")

    return success_response()


@router.post("/api/devices/{device_id}/play")
async def device_play_url(
    device_id: str,
    url: str = Query(..., description="音频 URL")
):
    """让设备播放指定 URL"""
    from .websocket import manager
    from ..models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    await manager.send_request(device_id, ProtocolRequest.play_url(url))
    return success_response()


@router.post("/api/devices/{device_id}/speak")
async def device_speak(
    device_id: str,
    speak_text: str = Query(..., description="要播放的文本"),
    http_request: Request,
):
    """让设备播放语音 (TTS)"""
    from .websocket import manager
    from ..models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    tts_service = http_request.app.state.tts_service
    audio_url = await tts_service.synthesize_to_url(speak_text)

    await manager.send_request(device_id, ProtocolRequest.play_url(audio_url))
    return success_response(data={"audio_url": audio_url})


@router.post("/api/devices/{device_id}/pause")
async def device_pause(device_id: str):
    """暂停设备播放"""
    from .websocket import manager
    from ..models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    await manager.send_request(device_id, ProtocolRequest.pause())
    return success_response()


@router.post("/api/devices/{device_id}/resume")
async def device_resume(device_id: str):
    """继续设备播放"""
    from .websocket import manager
    from ..models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    await manager.send_request(device_id, ProtocolRequest.play())
    return success_response()


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


# ========== 统计 API ==========

@router.get("/api/v1/stats")
async def get_stats(
    http_request: Request,
    content_service: ContentService = Depends(get_content_service)
):
    """获取系统统计信息"""
    from .websocket import manager

    stats = await content_service.get_stats()

    return success_response(data={
        "connected_devices": len(manager.connections),
        "version": "0.1.0",
        **stats
    })


@router.get("/api/v1/stats/playback")
async def get_playback_stats(
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    content_service: ContentService = Depends(get_content_service)
):
    """播放统计 (日期范围)"""
    stats = await content_service.get_stats()
    return success_response(data={
        "total_plays": stats.get("total_play_count", 0),
        "total_duration": 0,
        "top_contents": [],
        "daily_stats": [],
    })


# ========== Admin Content CRUD API ==========

@router.get("/api/v1/admin/contents")
async def admin_list_contents(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    category_id: Optional[int] = Query(None, description="分类 ID"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    is_active: Optional[bool] = Query(None, description="是否激活"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """获取内容列表 (管理后台)"""
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)

    result = await content_service.list_contents(
        content_type=content_type,
        category_id=category_id,
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
    type_mapping = {
        "story": ContentType.STORY,
        "music": ContentType.MUSIC,
        "english": ContentType.ENGLISH
    }
    content_type = type_mapping.get(request.type)
    if not content_type:
        raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid content type: {request.type}")

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
    filename: str = Query(..., description="文件名"),
    folder: str = Query("stories", description="文件夹: stories, music, english, covers"),
    http_request: Request,
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
