"""
分类/艺术家/标签 目录查询 Mixin

包含分类树、艺术家列表、标签列表等公开查询
"""

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ...models.database import (
    Content, ContentType, Category, Artist, Tag,
    ArtistType, TagType, ContentArtist, ContentTag
)

logger = logging.getLogger(__name__)


class CatalogMixin:
    """分类/艺术家/标签 目录查询"""

    async def get_category_tree(
        self,
        content_type: Optional[ContentType] = None
    ) -> List[Dict[str, Any]]:
        """获取分类树"""
        # 尝试从缓存获取
        if self.redis and content_type:
            cached = await self.redis.get_category_tree(content_type.value)
            if cached:
                return cached

        async with self.session_factory() as session:
            query = (
                select(Category)
                .where(Category.is_active == True)
                .order_by(Category.level, Category.sort_order)
            )
            if content_type:
                query = query.where(Category.type == content_type)

            result = await session.execute(query)
            categories = result.scalars().all()

            # 构建树形结构
            tree = self._build_category_tree(categories)

            # 缓存结果
            if self.redis and content_type:
                await self.redis.set_category_tree(content_type.value, tree)

            return tree

    async def get_category_by_id(self, category_id: int) -> Optional[Dict[str, Any]]:
        """获取单个分类"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Category).where(Category.id == category_id)
            )
            category = result.scalar_one_or_none()
            return category.to_dict() if category else None

    async def get_category_children(self, category_id: int) -> List[Dict[str, Any]]:
        """获取子分类列表"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Category)
                .where(Category.parent_id == category_id)
                .where(Category.is_active == True)
                .order_by(Category.sort_order)
            )
            categories = result.scalars().all()
            return [c.to_dict() for c in categories]

    async def list_artists(
        self,
        artist_type: Optional[ArtistType] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取艺术家列表（分页）"""
        async with self.session_factory() as session:
            conditions = [Artist.is_active == True]

            if artist_type:
                conditions.append(Artist.type == artist_type)
            if keyword:
                conditions.append(
                    or_(
                        Artist.name.contains(keyword),
                        Artist.name_pinyin.contains(keyword),
                        Artist.aliases.contains(keyword)
                    )
                )

            # 统计总数
            count_query = select(func.count()).select_from(Artist).where(and_(*conditions))
            result = await session.execute(count_query)
            total = result.scalar()

            # 分页查询
            query = (
                select(Artist)
                .where(and_(*conditions))
                .order_by(Artist.name)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )

            result = await session.execute(query)
            artists = result.scalars().all()

            return {
                "items": [a.to_dict() for a in artists],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }

    async def get_artist_by_id(self, artist_id: int) -> Optional[Dict[str, Any]]:
        """获取单个艺术家"""
        # 尝试缓存
        if self.redis:
            cached = await self.redis.get_artist(artist_id)
            if cached:
                return cached

        async with self.session_factory() as session:
            result = await session.execute(
                select(Artist).where(Artist.id == artist_id)
            )
            artist = result.scalar_one_or_none()

            if artist:
                data = artist.to_dict()
                if self.redis:
                    await self.redis.set_artist(artist_id, data)
                return data
            return None

    async def get_contents_by_artist(
        self,
        artist_id: int,
        content_type: Optional[ContentType] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取艺术家的内容列表（分页）"""
        async with self.session_factory() as session:
            conditions = [
                ContentArtist.artist_id == artist_id,
                Content.is_active == True
            ]

            if content_type:
                conditions.append(Content.type == content_type)

            # 统计总数
            count_query = (
                select(func.count(func.distinct(Content.id)))
                .select_from(Content)
                .join(ContentArtist)
                .where(and_(*conditions))
            )
            result = await session.execute(count_query)
            total = result.scalar()

            # 分页查询
            query = (
                select(Content)
                .join(ContentArtist)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(and_(*conditions))
                .order_by(ContentArtist.is_primary.desc(), Content.play_count.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )

            result = await session.execute(query)
            contents = result.scalars().unique().all()

            return {
                "items": [await self._content_to_dict(c) for c in contents],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }

    async def list_tags(
        self,
        tag_type: Optional[TagType] = None
    ) -> List[Dict[str, Any]]:
        """获取标签列表"""
        # 尝试缓存
        if self.redis and tag_type:
            cached = await self.redis.get_tag_list(tag_type.value)
            if cached:
                return cached

        async with self.session_factory() as session:
            query = select(Tag).where(Tag.is_active == True)

            if tag_type:
                query = query.where(Tag.type == tag_type)

            query = query.order_by(Tag.type, Tag.sort_order)

            result = await session.execute(query)
            tags = result.scalars().all()

            tag_list = [t.to_dict() for t in tags]

            # 缓存
            if self.redis and tag_type:
                await self.redis.set_tag_list(tag_type.value, tag_list)

            return tag_list

    async def get_tag_by_id(self, tag_id: int) -> Optional[Dict[str, Any]]:
        """获取单个标签"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Tag).where(Tag.id == tag_id)
            )
            tag = result.scalar_one_or_none()
            return tag.to_dict() if tag else None

    async def get_contents_by_tag(
        self,
        tag_id: int,
        content_type: Optional[ContentType] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取标签下的内容列表（分页）"""
        async with self.session_factory() as session:
            conditions = [
                ContentTag.tag_id == tag_id,
                Content.is_active == True
            ]

            if content_type:
                conditions.append(Content.type == content_type)

            # 统计总数
            count_query = (
                select(func.count(func.distinct(Content.id)))
                .select_from(Content)
                .join(ContentTag)
                .where(and_(*conditions))
            )
            result = await session.execute(count_query)
            total = result.scalar()

            # 分页查询
            query = (
                select(Content)
                .join(ContentTag)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(and_(*conditions))
                .order_by(Content.play_count.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )

            result = await session.execute(query)
            contents = result.scalars().unique().all()

            return {
                "items": [await self._content_to_dict(c) for c in contents],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }
