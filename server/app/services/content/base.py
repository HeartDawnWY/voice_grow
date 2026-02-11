"""
ContentService 基础类

包含初始化、通用转换方法
"""

import logging
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from ...models.database import Content, Category
from ..minio_service import MinIOService

if TYPE_CHECKING:
    from ..redis_service import RedisService

logger = logging.getLogger(__name__)


class ContentServiceBase:
    """内容服务基础类（提供 __init__ 和通用工具方法）"""

    def __init__(
        self,
        session_factory,
        minio_service: MinIOService,
        redis_service: Optional["RedisService"] = None
    ):
        """
        初始化内容服务

        Args:
            session_factory: SQLAlchemy 异步会话工厂
            minio_service: MinIO 服务实例
            redis_service: Redis 缓存服务实例
        """
        self.session_factory = session_factory
        self.minio = minio_service
        self.redis = redis_service

    async def _content_to_dict(self, content: Content) -> Dict[str, Any]:
        """转换内容为字典，并生成播放 URL"""
        if content.minio_path and content.minio_path.startswith("http"):
            play_url = content.minio_path
        else:
            play_url = await self.minio.get_presigned_url(content.minio_path) if content.minio_path else None

        result = {
            "id": content.id,
            "type": content.type.value,
            "category_id": content.category_id,
            "category_name": content.category.name if content.category else None,
            "title": content.title,
            "title_pinyin": content.title_pinyin,
            "description": content.description,
            "play_url": play_url,
            "minio_path": content.minio_path,
            "duration": content.duration,
            "play_count": content.play_count,
            "artists": [],
            "tags": [],
        }

        # 添加艺术家信息
        if content.content_artists:
            result["artists"] = [
                {
                    "id": ca.artist.id,
                    "name": ca.artist.name,
                    "role": ca.role.value,
                    "is_primary": ca.is_primary
                }
                for ca in content.content_artists
            ]

        # 添加标签信息
        if content.content_tags:
            result["tags"] = [
                {
                    "id": ct.tag.id,
                    "name": ct.tag.name,
                    "type": ct.tag.type.value
                }
                for ct in content.content_tags
            ]

        return result

    async def _content_to_admin_dict(self, content: Content) -> Dict[str, Any]:
        """转换内容为管理字典"""
        result = {
            "id": content.id,
            "type": content.type.value,
            "category_id": content.category_id,
            "category_name": content.category.name if content.category else None,
            "title": content.title,
            "title_pinyin": content.title_pinyin,
            "subtitle": content.subtitle,
            "description": content.description,
            "minio_path": content.minio_path,
            "cover_path": content.cover_path,
            "duration": content.duration,
            "file_size": content.file_size,
            "format": content.format,
            "bitrate": content.bitrate,
            "age_min": content.age_min,
            "age_max": content.age_max,
            "play_count": content.play_count,
            "like_count": content.like_count,
            "is_active": content.is_active,
            "is_vip": content.is_vip,
            "created_at": content.created_at.isoformat() if content.created_at else None,
            "updated_at": content.updated_at.isoformat() if content.updated_at else None,
            "published_at": content.published_at.isoformat() if content.published_at else None,
            "artists": [],
            "tags": [],
        }

        # 添加艺术家信息
        if content.content_artists:
            result["artists"] = [
                ca.artist.to_dict() | {"role": ca.role.value, "is_primary": ca.is_primary}
                for ca in content.content_artists
            ]

        # 添加标签信息
        if content.content_tags:
            result["tags"] = [ct.tag.to_dict() for ct in content.content_tags]

        # 生成 URL
        if content.minio_path:
            try:
                if content.minio_path.startswith("http"):
                    result["play_url"] = content.minio_path
                else:
                    result["play_url"] = await self.minio.get_presigned_url(content.minio_path)
            except Exception:
                result["play_url"] = None

        if content.cover_path:
            try:
                result["cover_url"] = await self.minio.get_presigned_url(content.cover_path)
            except Exception:
                result["cover_url"] = None

        return result

    def _build_category_tree(
        self,
        categories: List[Category],
        parent_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """构建分类树"""
        result = []
        for cat in categories:
            if cat.parent_id == parent_id:
                node = cat.to_dict()
                node["children"] = self._build_category_tree(categories, cat.id)
                result.append(node)
        return result
