"""
内容搜索 Mixin

包含智能搜索、按艺术家/标签/分类搜索
"""

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ...models.database import (
    Content, ContentType, Category, Artist, Tag,
    ContentArtist, ContentTag
)

logger = logging.getLogger(__name__)


class ContentSearchMixin:
    """内容搜索"""

    async def smart_search(
        self,
        keyword: str,
        content_type: Optional[ContentType] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        智能综合搜索

        搜索标题、艺术家、分类、标签，支持拼音

        Args:
            keyword: 搜索关键词
            content_type: 内容类型（可选）
            limit: 返回数量

        Example:
            results = await service.smart_search("睡前故事")
            results = await service.smart_search("周杰伦")
        """
        # 尝试从缓存获取
        if self.redis:
            cached = await self.redis.get_search_result(
                keyword,
                content_type.value if content_type else None
            )
            if cached:
                # 根据 ID 列表获取内容
                results = []
                for cid in cached[:limit]:
                    content = await self.get_content_by_id(cid)
                    if content:
                        results.append(content)
                return results

        async with self.session_factory() as session:
            query = (
                select(Content)
                .outerjoin(ContentArtist)
                .outerjoin(Artist)
                .outerjoin(Category, Content.category_id == Category.id)
                .outerjoin(ContentTag)
                .outerjoin(Tag)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(Content.is_active == True)
                .where(
                    or_(
                        Content.title.like(f"%{keyword}%"),
                        Content.title_pinyin.like(f"%{keyword}%"),
                        Artist.name.like(f"%{keyword}%"),
                        Artist.name_pinyin.like(f"%{keyword}%"),
                        Category.name.like(f"%{keyword}%"),
                        Category.name_pinyin.like(f"%{keyword}%"),
                        Tag.name.like(f"%{keyword}%"),
                        Tag.name_pinyin.like(f"%{keyword}%")
                    )
                )
                .distinct()
            )

            if content_type:
                query = query.where(Content.type == content_type)

            query = query.order_by(Content.play_count.desc()).limit(limit)

            result = await session.execute(query)
            contents = result.scalars().unique().all()

            results = [await self._content_to_dict(c) for c in contents]

            # 缓存搜索结果
            if self.redis and results:
                content_ids = [r["id"] for r in results]
                await self.redis.set_search_result(
                    keyword,
                    content_ids,
                    content_type.value if content_type else None
                )

            return results

    async def search_by_artist(
        self,
        artist_name: str,
        content_type: Optional[ContentType] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        按艺术家查询

        Args:
            artist_name: 艺术家名称（支持拼音）
            content_type: 内容类型 (story/music/english/sound)
            limit: 返回数量

        Example:
            # 想听王力宏的歌
            results = await service.search_by_artist("王力宏", ContentType.MUSIC)
            # 支持拼音
            results = await service.search_by_artist("wanglihong", ContentType.MUSIC)
        """
        async with self.session_factory() as session:
            query = (
                select(Content)
                .join(ContentArtist)
                .join(Artist)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(
                    or_(
                        Artist.name == artist_name,
                        Artist.name_pinyin.like(f"{artist_name}%"),
                        Artist.aliases.contains(artist_name)
                    )
                )
                .where(Content.is_active == True)
            )

            if content_type:
                query = query.where(Content.type == content_type)

            query = (
                query
                .order_by(ContentArtist.is_primary.desc(), Content.play_count.desc())
                .limit(limit)
            )

            result = await session.execute(query)
            contents = result.scalars().unique().all()

            return [await self._content_to_dict(c) for c in contents]

    async def search_by_artist_and_title(
        self,
        artist_name: str,
        title_keyword: str
    ) -> Optional[Dict[str, Any]]:
        """
        按艺术家+标题精确查询

        Example:
            # 播放周杰伦的晴天
            result = await service.search_by_artist_and_title("周杰伦", "晴天")
        """
        async with self.session_factory() as session:
            query = (
                select(Content)
                .join(ContentArtist)
                .join(Artist)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(
                    or_(
                        Artist.name == artist_name,
                        Artist.name_pinyin.like(f"{artist_name}%")
                    )
                )
                .where(
                    or_(
                        Content.title.like(f"%{title_keyword}%"),
                        Content.title_pinyin.like(f"%{title_keyword}%")
                    )
                )
                .where(Content.is_active == True)
                .order_by(
                    func.length(Content.title),
                    ContentArtist.is_primary.desc()
                )
                .limit(1)
            )

            result = await session.execute(query)
            content = result.scalar_one_or_none()

            if content:
                return await self._content_to_dict(content)
            return None

    async def search_by_tags(
        self,
        tag_names: List[str],
        content_type: Optional[ContentType] = None,
        match_all: bool = False,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        按标签组合查询

        Args:
            tag_names: 标签名列表
            content_type: 内容类型
            match_all: True=必须匹配所有标签，False=匹配任一标签
            limit: 返回数量

        Example:
            # 播放胎教故事
            results = await service.search_by_tags(["胎教"], ContentType.STORY)
            # 播放少儿英语
            results = await service.search_by_tags(["少儿", "英语"], ContentType.STORY)
        """
        async with self.session_factory() as session:
            # 构建基础查询
            query = (
                select(Content, func.count(ContentTag.tag_id).label('match_count'))
                .join(ContentTag)
                .join(Tag)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(
                    or_(
                        Tag.name.in_(tag_names),
                        Tag.name_pinyin.in_(tag_names)
                    )
                )
                .where(Content.is_active == True)
            )

            if content_type:
                query = query.where(Content.type == content_type)

            query = query.group_by(Content.id)

            if match_all:
                query = query.having(func.count(ContentTag.tag_id) >= len(tag_names))

            query = (
                query
                .order_by(func.count(ContentTag.tag_id).desc(), Content.play_count.desc())
                .limit(limit)
            )

            result = await session.execute(query)
            rows = result.all()

            return [await self._content_to_dict(row[0]) for row in rows]

    async def search_by_category(
        self,
        category_name: str,
        include_children: bool = True,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        按分类查询

        Args:
            category_name: 分类名称（支持拼音）
            include_children: 是否包含子分类
            limit: 返回数量

        Example:
            # 播放童话故事（包含格林童话、安徒生童话等子分类）
            results = await service.search_by_category("童话故事", include_children=True)
        """
        async with self.session_factory() as session:
            # 先查找分类
            cat_query = select(Category).where(
                or_(
                    Category.name == category_name,
                    Category.name_pinyin.like(f"{category_name}%")
                )
            )
            cat_result = await session.execute(cat_query)
            category = cat_result.scalar_one_or_none()

            if not category:
                return []

            # 构建查询
            query = (
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(Content.is_active == True)
            )

            if include_children and category.path:
                # 包含子分类：使用 path 前缀匹配
                subquery = select(Category.id).where(
                    Category.path.like(f"{category.path}%")
                )
                query = query.where(Content.category_id.in_(subquery))
            else:
                query = query.where(Content.category_id == category.id)

            query = query.order_by(Content.play_count.desc()).limit(limit)

            result = await session.execute(query)
            contents = result.scalars().all()

            return [await self._content_to_dict(c) for c in contents]
