"""
内容基础查询 Mixin

包含按 ID、名称、类型查询内容
"""

import logging
import random
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ...models.database import (
    Content, ContentType, Category, ContentArtist, ContentTag
)

logger = logging.getLogger(__name__)


class ContentQueryMixin:
    """内容基础查询"""

    async def get_content_by_id(
        self,
        content_id: int,
        include_inactive: bool = False,
        admin_view: bool = False
    ) -> Optional[Dict[str, Any]]:
        """根据 ID 获取内容"""
        # 尝试从缓存获取
        if self.redis and not admin_view:
            cached = await self.redis.get_content(content_id)
            if cached:
                return cached

        async with self.session_factory() as session:
            query = (
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(Content.id == content_id)
            )
            if not include_inactive:
                query = query.where(Content.is_active == True)

            result = await session.execute(query)
            content = result.scalar_one_or_none()

            if content:
                if admin_view:
                    return await self._content_to_admin_dict(content)
                data = await self._content_to_dict(content)
                # 缓存结果
                if self.redis:
                    await self.redis.set_content(content_id, data)
                return data

            return None

    async def get_random_story(
        self,
        category_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取随机故事"""
        return await self._get_random_content(ContentType.STORY, category_name)

    async def get_random_music(
        self,
        category_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取随机音乐"""
        return await self._get_random_content(ContentType.MUSIC, category_name)

    async def _get_random_content(
        self,
        content_type: ContentType,
        category_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取随机内容"""
        async with self.session_factory() as session:
            conditions = [
                Content.type == content_type,
                Content.is_active == True
            ]

            # 如果指定了分类名称，查找分类ID
            if category_name:
                cat_result = await session.execute(
                    select(Category).where(
                        or_(
                            Category.name == category_name,
                            Category.name_pinyin.like(f"{category_name}%")
                        )
                    )
                )
                category = cat_result.scalar_one_or_none()
                if category:
                    # 包含子分类
                    if category.path:
                        subquery = select(Category.id).where(
                            Category.path.like(f"{category.path}%")
                        )
                        conditions.append(Content.category_id.in_(subquery))
                    else:
                        conditions.append(Content.category_id == category.id)

            # 获取符合条件的内容数量
            count_query = select(func.count()).select_from(Content).where(and_(*conditions))
            result = await session.execute(count_query)
            count = result.scalar()

            if count == 0:
                logger.warning(f"没有找到内容: type={content_type}, category={category_name}")
                return None

            # 随机选择
            offset = random.randint(0, count - 1)
            query = (
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(and_(*conditions))
                .offset(offset)
                .limit(1)
            )

            result = await session.execute(query)
            content = result.scalar_one_or_none()

            if content:
                return await self._content_to_dict(content)

            return None

    async def get_content_by_name(
        self,
        content_type: ContentType,
        name: str
    ) -> Optional[Dict[str, Any]]:
        """根据名称获取内容"""
        async with self.session_factory() as session:
            # 先尝试精确匹配
            query = (
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(
                    and_(
                        Content.type == content_type,
                        Content.is_active == True,
                        or_(
                            Content.title == name,
                            Content.title_pinyin == name
                        )
                    )
                )
            )
            result = await session.execute(query)
            content = result.scalar_one_or_none()

            # 如果没有精确匹配，尝试模糊匹配
            if not content:
                query = (
                    select(Content)
                    .options(
                        selectinload(Content.category),
                        selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                        selectinload(Content.content_tags).selectinload(ContentTag.tag)
                    )
                    .where(
                        and_(
                            Content.type == content_type,
                            Content.is_active == True,
                            or_(
                                Content.title.contains(name),
                                Content.title_pinyin.contains(name)
                            )
                        )
                    )
                    .limit(1)
                )
                result = await session.execute(query)
                content = result.scalar_one_or_none()

            if content:
                return await self._content_to_dict(content)

            return None

    async def search_content(
        self,
        content_type: ContentType,
        keyword: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """搜索内容（兼容旧接口）"""
        return await self.smart_search(keyword, content_type, limit)
