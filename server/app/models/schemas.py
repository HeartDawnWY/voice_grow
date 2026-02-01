"""
Pydantic 请求/响应模型

从 http.py 中提取的所有 Pydantic 模型
"""

from typing import Optional, List, Dict, Any

from pydantic import BaseModel


# ========== 请求模型 ==========

class ContentCreateRequest(BaseModel):
    """创建内容请求"""
    type: str  # story, music, english
    title: str
    category_id: int
    title_pinyin: Optional[str] = None
    subtitle: Optional[str] = None
    description: str = ""
    minio_path: str = ""
    cover_path: str = ""
    duration: int = 0
    age_min: int = 0
    age_max: int = 12
    artist_ids: Optional[List[dict]] = None  # [{"id": 1, "role": "singer", "is_primary": true}]
    tag_ids: Optional[List[int]] = None


class ContentUpdateRequest(BaseModel):
    """更新内容请求"""
    title: Optional[str] = None
    title_pinyin: Optional[str] = None
    subtitle: Optional[str] = None
    category_id: Optional[int] = None
    description: Optional[str] = None
    minio_path: Optional[str] = None
    cover_path: Optional[str] = None
    duration: Optional[int] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    is_active: Optional[bool] = None


class WordCreateRequest(BaseModel):
    """创建单词请求"""
    word: str
    phonetic_us: str = ""
    phonetic_uk: str = ""
    translation: str
    audio_us_path: str = ""
    audio_uk_path: str = ""
    level: str = "basic"
    category_id: Optional[int] = None
    example_sentence: str = ""
    example_translation: str = ""


class WordUpdateRequest(BaseModel):
    """更新单词请求"""
    phonetic_us: Optional[str] = None
    phonetic_uk: Optional[str] = None
    translation: Optional[str] = None
    audio_us_path: Optional[str] = None
    audio_uk_path: Optional[str] = None
    level: Optional[str] = None
    category_id: Optional[int] = None
    example_sentence: Optional[str] = None
    example_translation: Optional[str] = None


class CategoryCreateRequest(BaseModel):
    """创建分类请求"""
    name: str
    type: str  # story, music, english
    parent_id: Optional[int] = None
    description: str = ""
    icon: str = ""
    sort_order: int = 0


class CategoryUpdateRequest(BaseModel):
    """更新分类请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ArtistCreateRequest(BaseModel):
    """创建艺术家请求"""
    name: str
    type: str  # narrator, singer, composer, author, band
    avatar: str = ""
    description: str = ""


class ArtistUpdateRequest(BaseModel):
    """更新艺术家请求"""
    name: Optional[str] = None
    type: Optional[str] = None
    avatar: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class TagCreateRequest(BaseModel):
    """创建标签请求"""
    name: str
    type: str  # theme, mood, age, scene, feature
    color: str = ""
    sort_order: int = 0


class TagUpdateRequest(BaseModel):
    """更新标签请求"""
    name: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class DeviceCommandRequest(BaseModel):
    """设备命令请求"""
    command: str
    params: Dict[str, Any] = {}


# ========== 响应模型 ==========

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
    phonetic_us: Optional[str] = None
    phonetic_uk: Optional[str] = None
    translation: str
    audio_us_url: Optional[str] = None
    audio_uk_url: Optional[str] = None
    example: Optional[str] = None


class CategoryResponse(BaseModel):
    """分类响应"""
    id: int
    name: str
    name_pinyin: Optional[str] = None
    type: str
    level: int
    parent_id: Optional[int] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    children: List["CategoryResponse"] = []


class CategoryListResponse(BaseModel):
    """分类列表响应"""
    categories: List[CategoryResponse]


class ArtistResponse(BaseModel):
    """艺术家响应"""
    id: int
    name: str
    name_pinyin: Optional[str] = None
    type: str
    avatar: Optional[str] = None
    description: Optional[str] = None


class ArtistListResponse(BaseModel):
    """艺术家列表响应"""
    items: List[ArtistResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TagResponse(BaseModel):
    """标签响应"""
    id: int
    name: str
    name_pinyin: Optional[str] = None
    type: str
    color: Optional[str] = None


class TagListResponse(BaseModel):
    """标签列表响应"""
    tags: List[TagResponse]


class SearchResultResponse(BaseModel):
    """搜索结果响应"""
    results: List[ContentResponse]
    total: int


class PaginatedContentResponse(BaseModel):
    """分页内容响应"""
    items: List[ContentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeviceDetailResponse(BaseModel):
    """设备详情响应"""
    device_id: str
    state: str
    playing_state: str
    current_content: Optional[Dict[str, Any]] = None


class HealthDetailResponse(BaseModel):
    """详细健康检查响应"""
    status: str
    version: str
    components: Dict[str, Any]


class PlaybackStatsResponse(BaseModel):
    """播放统计响应"""
    total_plays: int
    total_duration: int
    top_contents: List[Dict[str, Any]] = []
    daily_stats: List[Dict[str, Any]] = []


# 解析自引用模型
CategoryResponse.model_rebuild()
