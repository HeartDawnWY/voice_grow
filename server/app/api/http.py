"""
HTTP REST API

提供内容管理、健康检查等 HTTP 接口
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..models.database import ContentType, Content, EnglishWord
from ..services.content_service import ContentService

router = APIRouter()


# ========== Admin 请求/响应模型 ==========

class ContentCreateRequest(BaseModel):
    """创建内容请求"""
    type: str  # story, music, english
    title: str
    category: str = ""
    description: str = ""
    minio_path: str = ""
    cover_path: str = ""
    duration: int = 0
    tags: str = ""
    age_min: int = 0
    age_max: int = 12


class ContentUpdateRequest(BaseModel):
    """更新内容请求"""
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    minio_path: Optional[str] = None
    cover_path: Optional[str] = None
    duration: Optional[int] = None
    tags: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    is_active: Optional[bool] = None


class WordCreateRequest(BaseModel):
    """创建单词请求"""
    word: str
    phonetic: str = ""
    translation: str
    audio_us_path: str = ""
    audio_uk_path: str = ""
    level: str = "basic"
    category: str = ""
    example_sentence: str = ""
    example_translation: str = ""


class WordUpdateRequest(BaseModel):
    """更新单词请求"""
    phonetic: Optional[str] = None
    translation: Optional[str] = None
    audio_us_path: Optional[str] = None
    audio_uk_path: Optional[str] = None
    level: Optional[str] = None
    category: Optional[str] = None
    example_sentence: Optional[str] = None
    example_translation: Optional[str] = None
logger = logging.getLogger(__name__)


# ========== 依赖注入 ==========

async def get_content_service(request: Request) -> ContentService:
    """获取内容服务实例"""
    return request.app.state.content_service


# ========== 请求/响应模型 ==========

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str


class ContentResponse(BaseModel):
    """内容响应"""
    id: int
    type: str
    category: str
    title: str
    description: Optional[str] = None
    play_url: str
    duration: Optional[int] = None
    tags: List[str] = []


class ContentListResponse(BaseModel):
    """内容列表响应"""
    items: List[ContentResponse]
    total: int


class WordResponse(BaseModel):
    """单词响应"""
    word: str
    phonetic: Optional[str] = None
    translation: str
    audio_us_url: Optional[str] = None
    audio_uk_url: Optional[str] = None
    example: Optional[str] = None


# ========== 健康检查 ==========

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查接口

    Returns:
        服务状态
    """
    return HealthResponse(
        status="ok",
        version="0.1.0"
    )


@router.get("/ready")
async def readiness_check(request: Request):
    """
    就绪检查接口

    检查所有依赖服务是否就绪
    """
    checks = {
        "database": False,
        "minio": False,
        "redis": False
    }

    # 检查数据库连接
    try:
        engine = request.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            checks["database"] = True
    except Exception as e:
        logger.error(f"数据库检查失败: {e}")

    # 检查 MinIO
    try:
        minio = request.app.state.minio_service
        # MinIO 客户端在首次使用时初始化
        checks["minio"] = True
    except Exception as e:
        logger.error(f"MinIO 检查失败: {e}")

    # Redis 检查 (如果有 session_service)
    if hasattr(request.app.state, 'session_service'):
        try:
            session_service = request.app.state.session_service
            checks["redis"] = await session_service.ping()
        except Exception as e:
            logger.error(f"Redis 检查失败: {e}")
    else:
        checks["redis"] = True  # 没有 session_service 时跳过

    all_ready = all(checks.values())

    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks
    }


# ========== 内容 API ==========

@router.get("/api/contents", response_model=ContentListResponse)
async def list_contents(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    category: Optional[str] = Query(None, description="内容分类"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取内容列表

    Args:
        type: 内容类型
        category: 分类
        keyword: 搜索关键词
        limit: 返回数量
        offset: 偏移量

    Returns:
        内容列表
    """
    # 转换内容类型
    content_type = None
    if type:
        type_mapping = {
            "story": ContentType.STORY,
            "music": ContentType.MUSIC,
            "english": ContentType.ENGLISH
        }
        content_type = type_mapping.get(type)
        if not content_type:
            raise HTTPException(status_code=400, detail=f"Invalid content type: {type}")

    # 搜索内容
    if keyword:
        if content_type:
            items = await content_service.search_content(content_type, keyword, limit)
        else:
            # 搜索所有类型
            items = []
            for ct in ContentType:
                results = await content_service.search_content(ct, keyword, limit // 3)
                items.extend(results)
    else:
        # 获取列表 (暂时返回空，需要实现 list_contents 方法)
        items = []

    return ContentListResponse(
        items=[
            ContentResponse(
                id=item["id"],
                type=item["type"],
                category=item.get("category", ""),
                title=item["title"],
                description=item.get("description"),
                play_url=item["play_url"],
                duration=item.get("duration"),
                tags=item.get("tags", [])
            )
            for item in items
        ],
        total=len(items)
    )


@router.get("/api/contents/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取单个内容

    Args:
        content_id: 内容 ID

    Returns:
        内容详情
    """
    content = await content_service.get_content_by_id(content_id)

    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

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


@router.get("/api/stories/random", response_model=ContentResponse)
async def get_random_story(
    category: Optional[str] = Query(None, description="故事分类"),
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取随机故事

    Args:
        category: 故事分类

    Returns:
        随机故事
    """
    content = await content_service.get_random_story(category)

    if not content:
        raise HTTPException(status_code=404, detail="No stories found")

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


@router.get("/api/music/random", response_model=ContentResponse)
async def get_random_music(
    category: Optional[str] = Query(None, description="音乐分类"),
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取随机音乐

    Args:
        category: 音乐分类

    Returns:
        随机音乐
    """
    content = await content_service.get_random_music(category)

    if not content:
        raise HTTPException(status_code=404, detail="No music found")

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

@router.get("/api/english/word/{word}", response_model=WordResponse)
async def get_word(
    word: str,
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取单词信息

    Args:
        word: 单词

    Returns:
        单词详情
    """
    word_info = await content_service.get_word(word)

    if not word_info:
        raise HTTPException(status_code=404, detail="Word not found")

    return WordResponse(
        word=word_info["word"],
        phonetic=word_info.get("phonetic"),
        translation=word_info["translation"],
        audio_us_url=word_info.get("audio_us_url"),
        audio_uk_url=word_info.get("audio_uk_url"),
        example=word_info.get("example")
    )


@router.get("/api/english/random", response_model=WordResponse)
async def get_random_word(
    level: Optional[str] = Query(None, description="级别: basic, elementary, intermediate"),
    category: Optional[str] = Query(None, description="分类: animal, food, color"),
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取随机单词

    Args:
        level: 级别
        category: 分类

    Returns:
        随机单词
    """
    word_info = await content_service.get_random_word(level, category)

    if not word_info:
        raise HTTPException(status_code=404, detail="No words found")

    return WordResponse(
        word=word_info["word"],
        phonetic=word_info.get("phonetic"),
        translation=word_info["translation"],
        audio_us_url=word_info.get("audio_us_url"),
        audio_uk_url=word_info.get("audio_uk_url"),
        example=word_info.get("example")
    )


# ========== 分类 API ==========

@router.get("/api/categories")
async def get_categories(
    type: str = Query(..., description="内容类型: story, music")
):
    """
    获取分类列表

    Args:
        type: 内容类型

    Returns:
        分类列表
    """
    # 分类定义
    categories = {
        "story": [
            {"id": "bedtime", "name": "睡前故事", "description": "适合睡前听的温馨故事"},
            {"id": "fairy_tale", "name": "童话故事", "description": "经典童话故事"},
            {"id": "fable", "name": "寓言故事", "description": "富有哲理的寓言"},
            {"id": "science", "name": "科普故事", "description": "科学知识故事"},
            {"id": "idiom", "name": "成语故事", "description": "成语典故"},
            {"id": "history", "name": "历史故事", "description": "历史人物故事"},
            {"id": "myth", "name": "神话故事", "description": "中外神话传说"},
        ],
        "music": [
            {"id": "nursery_rhyme", "name": "儿歌", "description": "经典儿歌"},
            {"id": "lullaby", "name": "摇篮曲", "description": "睡眠音乐"},
            {"id": "classical", "name": "古典音乐", "description": "古典名曲"},
            {"id": "english", "name": "英文歌", "description": "英文儿歌"},
        ]
    }

    if type not in categories:
        raise HTTPException(status_code=400, detail=f"Invalid type: {type}")

    return {"categories": categories[type]}


# ========== 设备管理 API ==========

@router.get("/api/devices")
async def list_devices():
    """
    获取已连接的设备列表

    Returns:
        设备列表
    """
    from .websocket import manager

    devices = []
    for device_id, conn in manager.connections.items():
        devices.append({
            "device_id": device_id,
            "state": conn.state.value,
            "playing_state": conn.playing_state.value,
        })

    return {"devices": devices, "total": len(devices)}


@router.post("/api/devices/{device_id}/play")
async def device_play_url(
    device_id: str,
    url: str = Query(..., description="音频 URL")
):
    """
    让设备播放指定 URL

    Args:
        device_id: 设备 ID
        url: 音频 URL

    Returns:
        操作结果
    """
    from .websocket import manager
    from ..models.protocol import Request

    conn = manager.get_connection(device_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Device not connected")

    await manager.send_request(device_id, Request.play_url(url))
    return {"status": "ok"}


@router.post("/api/devices/{device_id}/speak")
async def device_speak(
    device_id: str,
    speak_text: str = Query(..., description="要播放的文本"),
    http_request: Request = None
):
    """
    让设备播放语音 (TTS)

    Args:
        device_id: 设备 ID
        speak_text: 要播放的文本

    Returns:
        操作结果
    """
    from .websocket import manager
    from ..models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Device not connected")

    # 使用 TTS 服务合成语音
    tts_service = http_request.app.state.tts_service
    audio_url = await tts_service.synthesize_to_url(speak_text)

    await manager.send_request(device_id, ProtocolRequest.play_url(audio_url))
    return {"status": "ok", "audio_url": audio_url}


@router.post("/api/devices/{device_id}/pause")
async def device_pause(device_id: str):
    """暂停设备播放"""
    from .websocket import manager
    from ..models.protocol import Request

    conn = manager.get_connection(device_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Device not connected")

    await manager.send_request(device_id, Request.pause())
    return {"status": "ok"}


@router.post("/api/devices/{device_id}/resume")
async def device_resume(device_id: str):
    """继续设备播放"""
    from .websocket import manager
    from ..models.protocol import Request

    conn = manager.get_connection(device_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Device not connected")

    await manager.send_request(device_id, Request.play())
    return {"status": "ok"}


# ========== 播放历史 API ==========

@router.get("/api/devices/{device_id}/history")
async def get_device_history(
    device_id: str,
    limit: int = Query(10, ge=1, le=50),
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取设备播放历史

    Args:
        device_id: 设备 ID
        limit: 返回数量

    Returns:
        播放历史
    """
    history = await content_service.get_recent_history(device_id, limit)
    return {"history": history}


# ========== 统计 API ==========

@router.get("/api/stats")
async def get_stats(
    http_request: Request,
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取系统统计信息

    Returns:
        统计数据
    """
    from .websocket import manager

    # 获取各类内容统计
    stats = await content_service.get_stats()

    return {
        "connected_devices": len(manager.connections),
        "version": "0.1.0",
        **stats
    }


# ========== Admin Content CRUD API ==========

@router.get("/api/admin/contents")
async def admin_list_contents(
    type: Optional[str] = Query(None, description="内容类型: story, music, english"),
    category: Optional[str] = Query(None, description="分类"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    is_active: Optional[bool] = Query(None, description="是否激活"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取内容列表 (管理后台)

    Args:
        type: 内容类型
        category: 分类
        keyword: 搜索关键词
        is_active: 是否激活
        page: 页码
        page_size: 每页数量

    Returns:
        内容列表和分页信息
    """
    # 转换内容类型
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
        category=category,
        keyword=keyword,
        is_active=is_active,
        page=page,
        page_size=page_size
    )

    return result


@router.post("/api/admin/contents")
async def admin_create_content(
    request: ContentCreateRequest,
    http_request: Request,
    content_service: ContentService = Depends(get_content_service)
):
    """
    创建内容 (管理后台)

    Args:
        request: 创建内容请求

    Returns:
        创建的内容
    """
    # 转换内容类型
    type_mapping = {
        "story": ContentType.STORY,
        "music": ContentType.MUSIC,
        "english": ContentType.ENGLISH
    }
    content_type = type_mapping.get(request.type)
    if not content_type:
        raise HTTPException(status_code=400, detail=f"Invalid content type: {request.type}")

    content = await content_service.create_content(
        type=content_type,
        title=request.title,
        category=request.category,
        description=request.description,
        minio_path=request.minio_path,
        cover_path=request.cover_path,
        duration=request.duration,
        tags=request.tags,
        age_min=request.age_min,
        age_max=request.age_max
    )

    return {"status": "ok", "data": content}


@router.get("/api/admin/contents/{content_id}")
async def admin_get_content(
    content_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取单个内容详情 (管理后台)

    Args:
        content_id: 内容 ID

    Returns:
        内容详情
    """
    content = await content_service.get_content_by_id(content_id, include_inactive=True, admin_view=True)

    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    return {"status": "ok", "data": content}


@router.put("/api/admin/contents/{content_id}")
async def admin_update_content(
    content_id: int,
    request: ContentUpdateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """
    更新内容 (管理后台)

    Args:
        content_id: 内容 ID
        request: 更新内容请求

    Returns:
        更新后的内容
    """
    # 构建更新字段
    update_data = request.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    content = await content_service.update_content(content_id, update_data)

    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    return {"status": "ok", "data": content}


@router.delete("/api/admin/contents/{content_id}")
async def admin_delete_content(
    content_id: int,
    hard: bool = Query(False, description="是否物理删除"),
    content_service: ContentService = Depends(get_content_service)
):
    """
    删除内容 (管理后台)

    Args:
        content_id: 内容 ID
        hard: 是否物理删除，默认软删除

    Returns:
        操作结果
    """
    success = await content_service.delete_content(content_id, hard=hard)

    if not success:
        raise HTTPException(status_code=404, detail="Content not found")

    return {"status": "ok", "message": "Content deleted"}


# ========== Admin File Upload API ==========

@router.post("/api/admin/upload/presigned-url")
async def admin_get_upload_url(
    filename: str = Query(..., description="文件名"),
    folder: str = Query("stories", description="文件夹: stories, music, english, covers"),
    http_request: Request = None
):
    """
    获取预签名上传 URL

    Args:
        filename: 文件名
        folder: 目标文件夹

    Returns:
        预签名上传 URL 和对象路径
    """
    import re
    import uuid
    from datetime import datetime

    # 允许的文件扩展名白名单
    ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
    FOLDER_EXTENSIONS = {
        "stories": ALLOWED_AUDIO_EXTENSIONS,
        "music": ALLOWED_AUDIO_EXTENSIONS,
        "english": ALLOWED_AUDIO_EXTENSIONS,
        "covers": ALLOWED_IMAGE_EXTENSIONS,
    }

    # 验证文件夹
    if folder not in FOLDER_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Invalid folder: {folder}")

    # 提取并清理扩展名 (只保留字母数字，防止路径遍历)
    ext = ""
    if "." in filename:
        raw_ext = filename.rsplit(".", 1)[-1].lower()
        ext = re.sub(r'[^a-z0-9]', '', raw_ext)[:10]

    # 验证扩展名
    allowed_exts = FOLDER_EXTENSIONS[folder]
    if not ext or ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed for folder '{folder}'. Allowed: {', '.join(sorted(allowed_exts))}"
        )

    # 生成唯一文件名 (使用 UUID 确保安全，不使用原始文件名)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    object_name = f"{folder}/{timestamp}_{unique_id}.{ext}"

    # 获取预签名上传 URL
    minio_service = http_request.app.state.minio_service
    upload_url = await minio_service.presigned_put_url(object_name)

    return {
        "status": "ok",
        "upload_url": upload_url,
        "object_name": object_name
    }


# ========== Admin English Word CRUD API ==========

@router.get("/api/admin/words")
async def admin_list_words(
    level: Optional[str] = Query(None, description="级别: basic, elementary, intermediate"),
    category: Optional[str] = Query(None, description="分类: animal, food, color"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取单词列表 (管理后台)

    Args:
        level: 级别
        category: 分类
        keyword: 搜索关键词
        page: 页码
        page_size: 每页数量

    Returns:
        单词列表和分页信息
    """
    result = await content_service.list_words(
        level=level,
        category=category,
        keyword=keyword,
        page=page,
        page_size=page_size
    )

    return result


@router.post("/api/admin/words")
async def admin_create_word(
    request: WordCreateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """
    创建单词 (管理后台)

    Args:
        request: 创建单词请求

    Returns:
        创建的单词
    """
    word = await content_service.create_word(
        word=request.word,
        phonetic=request.phonetic,
        translation=request.translation,
        audio_us_path=request.audio_us_path,
        audio_uk_path=request.audio_uk_path,
        level=request.level,
        category=request.category,
        example_sentence=request.example_sentence,
        example_translation=request.example_translation
    )

    return {"status": "ok", "data": word}


@router.get("/api/admin/words/{word_id}")
async def admin_get_word(
    word_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """
    获取单个单词详情 (管理后台)

    Args:
        word_id: 单词 ID

    Returns:
        单词详情
    """
    word = await content_service.get_word_by_id(word_id)

    if not word:
        raise HTTPException(status_code=404, detail="Word not found")

    return {"status": "ok", "data": word}


@router.put("/api/admin/words/{word_id}")
async def admin_update_word(
    word_id: int,
    request: WordUpdateRequest,
    content_service: ContentService = Depends(get_content_service)
):
    """
    更新单词 (管理后台)

    Args:
        word_id: 单词 ID
        request: 更新单词请求

    Returns:
        更新后的单词
    """
    update_data = request.model_dump(exclude_none=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    word = await content_service.update_word(word_id, update_data)

    if not word:
        raise HTTPException(status_code=404, detail="Word not found")

    return {"status": "ok", "data": word}


@router.delete("/api/admin/words/{word_id}")
async def admin_delete_word(
    word_id: int,
    content_service: ContentService = Depends(get_content_service)
):
    """
    删除单词 (管理后台)

    Args:
        word_id: 单词 ID

    Returns:
        操作结果
    """
    success = await content_service.delete_word(word_id)

    if not success:
        raise HTTPException(status_code=404, detail="Word not found")

    return {"status": "ok", "message": "Word deleted"}
