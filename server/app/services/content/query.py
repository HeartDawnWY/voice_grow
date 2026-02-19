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
            try:
                cached = await self.redis.get_content(content_id)
                if cached:
                    return cached
            except Exception as e:
                logger.warning(f"Redis读取内容缓存失败(id={content_id})，回退DB: {e}")

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
                # 缓存结果（非关键操作）
                if self.redis:
                    try:
                        await self.redis.set_content(content_id, data)
                    except Exception as e:
                        logger.warning(f"Redis写入内容缓存失败(id={content_id}): {e}")
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
                category = await self._find_category(session, category_name)
                if category:
                    # 包含子分类
                    if category.path:
                        subquery = select(Category.id).where(
                            Category.path.like(f"{category.path}%")
                        )
                        conditions.append(Content.category_id.in_(subquery))
                    else:
                        conditions.append(Content.category_id == category.id)
                else:
                    logger.warning(f"未找到分类: {category_name}，不返回无过滤结果")
                    return None

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

    async def get_content_list(
        self,
        content_type: ContentType,
        category_name: Optional[str] = None,
        limit: int = 30,
        shuffle: bool = True
    ) -> List[Dict[str, Any]]:
        """获取内容列表（用于播放队列）

        Args:
            content_type: 内容类型
            category_name: 分类名称（可选）
            limit: 最大返回数量
            shuffle: 是否随机打乱顺序

        Returns:
            内容字典列表
        """
        async with self.session_factory() as session:
            conditions = [
                Content.type == content_type,
                Content.is_active == True
            ]

            # 查找分类
            if category_name:
                category = await self._find_category(session, category_name)
                if not category:
                    logger.warning(f"未找到分类: {category_name}")
                    return []

                # 包含子分类
                if category.path:
                    subquery = select(Category.id).where(
                        Category.path.like(f"{category.path}%")
                    )
                    conditions.append(Content.category_id.in_(subquery))
                else:
                    conditions.append(Content.category_id == category.id)

            query = (
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(and_(*conditions))
            )

            if shuffle:
                query = query.order_by(func.rand()).limit(limit)
            else:
                query = query.order_by(Content.play_count.desc()).limit(limit)

            result = await session.execute(query)
            contents = result.scalars().all()

            return [await self._content_to_dict(c) for c in contents]

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

    async def _find_category(self, session: "AsyncSession", category_name: str) -> Optional[Category]:
        """统一分类查找: 精确匹配 → 包含匹配 → 拼音前缀匹配

        解决 NLU 提取 '童话' 但数据库里叫 '童话故事' 的匹配问题。
        拼音步骤仅在输入为拼音时生效（如来自 LLM 或 API 调用）。
        """
        # 1. 精确匹配
        result = await session.execute(
            select(Category).where(Category.name == category_name)
        )
        category = result.scalar_one_or_none()
        if category:
            return category

        # 2. 包含匹配 (童话 → 童话故事)，按名称长度排序取最短匹配
        result = await session.execute(
            select(Category).where(
                Category.name.contains(category_name)
            ).order_by(func.char_length(Category.name)).limit(1)
        )
        category = result.scalars().first()
        if category:
            logger.info(f"分类模糊匹配: '{category_name}' → '{category.name}'")
            return category

        # 3. 拼音前缀匹配（仅当输入为拼音时生效）
        result = await session.execute(
            select(Category).where(
                Category.name_pinyin.like(f"{category_name}%")
            ).limit(1)
        )
        category = result.scalars().first()
        if category:
            logger.info(f"分类拼音匹配: '{category_name}' → '{category.name}'")
            return category

        return None

    async def search_content(
        self,
        content_type: ContentType,
        keyword: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """搜索内容（兼容旧接口）"""
        return await self.smart_search(keyword, content_type, limit)

    async def get_or_create_category(
        self,
        name: str,
        content_type: ContentType,
        description: str = "",
    ) -> int:
        """获取或创建分类，返回分类 ID"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Category).where(
                    and_(
                        Category.name == name,
                        Category.type == content_type,
                    )
                )
            )
            category = result.scalar_one_or_none()
            if category:
                return category.id

            new_cat = Category(
                name=name,
                type=content_type,
                level=1,
                path="",
                description=description or None,
            )
            session.add(new_cat)
            await session.commit()
            await session.refresh(new_cat)
            logger.info(f"创建分类: id={new_cat.id}, name={name}, type={content_type}")
            return new_cat.id

    async def get_artist_primary_category(
        self,
        artist_name: str,
        content_type: ContentType,
    ) -> Optional[int]:
        """查询某个歌手/作者在 DB 中已有内容的最常用分类 ID

        用于在线下载时复用歌手已有的分类，而非统一归到"在线搜索"。
        返回 None 表示该歌手在 DB 无历史内容。
        """
        from ...models.database import Artist

        async with self.session_factory() as session:
            # 找出该艺术家所有内容中出现最多的 category_id
            result = await session.execute(
                select(Content.category_id, func.count().label("cnt"))
                .join(ContentArtist)
                .join(Artist)
                .where(
                    and_(
                        Artist.name == artist_name,
                        Content.type == content_type,
                        Content.is_active == True,
                    )
                )
                .group_by(Content.category_id)
                .order_by(func.count().desc())
                .limit(1)
            )
            row = result.first()
            if row and row[0]:
                return row[0]
            return None
