"""
内容管理服务

管理故事、音乐、英语等内容的检索和播放
支持：
- 按艺术家搜索
- 按标签搜索
- 按分类层级搜索
- 拼音模糊搜索
- 智能综合搜索
"""

import logging
import random
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import (
    Content, ContentType, EnglishWord, PlayHistory,
    Category, Artist, Tag, ContentArtist, ContentTag,
    ArtistType, ArtistRole, TagType, WordLevel
)
from .minio_service import MinIOService

if TYPE_CHECKING:
    from .redis_service import RedisService

logger = logging.getLogger(__name__)


class ContentService:
    """
    内容管理服务

    负责内容检索、播放 URL 生成、播放历史记录等
    支持新的分类、艺术家、标签查询
    """

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

    # ========================================
    # 内容基础查询
    # ========================================

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

    # ========================================
    # 艺术家搜索
    # ========================================

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

    # ========================================
    # 标签搜索
    # ========================================

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

    # ========================================
    # 分类搜索
    # ========================================

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

    # ========================================
    # 智能综合搜索
    # ========================================

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

    async def search_content(
        self,
        content_type: ContentType,
        keyword: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """搜索内容（兼容旧接口）"""
        return await self.smart_search(keyword, content_type, limit)

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

    # ========================================
    # 分类管理
    # ========================================

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

    # ========================================
    # 艺术家管理
    # ========================================

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

    # ========================================
    # 标签管理
    # ========================================

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

    # ========================================
    # 英语学习
    # ========================================

    async def get_random_word(
        self,
        level: Optional[str] = None,
        category_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取随机单词"""
        async with self.session_factory() as session:
            conditions = []

            if level:
                try:
                    level_enum = WordLevel(level)
                    conditions.append(EnglishWord.level == level_enum)
                except ValueError:
                    pass

            if category_name:
                # 查找分类
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
                    conditions.append(EnglishWord.category_id == category.id)

            count_query = select(func.count()).select_from(EnglishWord)
            if conditions:
                count_query = count_query.where(and_(*conditions))
            result = await session.execute(count_query)
            count = result.scalar()

            if count == 0:
                return None

            offset = random.randint(0, count - 1)
            query = (
                select(EnglishWord)
                .options(selectinload(EnglishWord.category))
            )
            if conditions:
                query = query.where(and_(*conditions))
            query = query.offset(offset).limit(1)

            result = await session.execute(query)
            word = result.scalar_one_or_none()

            if word:
                return await self._word_to_dict(word)

            return None

    async def get_word(self, word: str) -> Optional[Dict[str, Any]]:
        """获取单词信息"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(EnglishWord)
                .options(selectinload(EnglishWord.category))
                .where(EnglishWord.word == word.lower())
            )
            word_obj = result.scalar_one_or_none()

            if word_obj:
                return await self._word_to_dict(word_obj)

            return None

    async def _word_to_dict(self, word: EnglishWord) -> Dict[str, Any]:
        """转换单词为字典"""
        result = {
            "id": word.id,
            "word": word.word,
            "phonetic_us": word.phonetic_us,
            "phonetic_uk": word.phonetic_uk,
            "translation": word.translation,
            "level": word.level.value if word.level else None,
            "category_id": word.category_id,
            "category_name": word.category.name if word.category else None,
            "example_sentence": word.example_sentence,
            "example_translation": word.example_translation,
            "created_at": word.created_at.isoformat() if word.created_at else None,
        }

        if word.audio_us_path:
            result["audio_us_url"] = await self.minio.get_presigned_url(word.audio_us_path)
        if word.audio_uk_path:
            result["audio_uk_url"] = await self.minio.get_presigned_url(word.audio_uk_path)

        return result

    # ========================================
    # 播放历史
    # ========================================

    async def record_play(
        self,
        device_id: str,
        content_id: int,
        content_type: ContentType,
        duration_played: Optional[int] = None,
        completed: bool = False,
        play_source: Optional[str] = None
    ):
        """记录播放历史"""
        async with self.session_factory() as session:
            history = PlayHistory(
                device_id=device_id,
                content_id=content_id,
                content_type=content_type,
                duration_played=duration_played or 0,
                completed=completed,
                play_source=play_source
            )
            session.add(history)
            await session.commit()

            logger.debug(f"记录播放历史: device={device_id}, content={content_id}")

        # 更新 Redis 播放历史和热门内容
        if self.redis:
            await self.redis.add_to_history(device_id, content_id)
            await self.redis.increment_play_count(content_type.value, content_id)

    async def get_recent_history(
        self,
        device_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取最近播放历史"""
        # 尝试从 Redis 获取
        if self.redis:
            content_ids = await self.redis.get_device_history(device_id, limit)
            if content_ids:
                results = []
                for cid in content_ids:
                    content = await self.get_content_by_id(cid)
                    if content:
                        results.append(content)
                return results

        async with self.session_factory() as session:
            result = await session.execute(
                select(PlayHistory)
                .options(selectinload(PlayHistory.content))
                .where(PlayHistory.device_id == device_id)
                .order_by(PlayHistory.played_at.desc())
                .limit(limit)
            )
            histories = result.scalars().all()

            return [
                {
                    "content_id": h.content_id,
                    "content_type": h.content_type.value,
                    "played_at": h.played_at.isoformat(),
                    "duration_played": h.duration_played,
                    "completed": h.completed,
                }
                for h in histories
            ]

    async def increment_play_count(self, content_id: int):
        """增加播放计数"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Content).where(Content.id == content_id)
            )
            content = result.scalar_one_or_none()

            if content:
                content.play_count += 1
                await session.commit()

                # 清除缓存
                if self.redis:
                    await self.redis.delete_content(content_id)

    # ========================================
    # 转换方法
    # ========================================

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

    # ========================================
    # Admin List (includes inactive records)
    # ========================================

    async def list_categories_admin(
        self,
        content_type: Optional[ContentType] = None
    ) -> List[Dict[str, Any]]:
        """获取分类树（管理端，包含停用记录）"""
        async with self.session_factory() as session:
            query = (
                select(Category)
                .order_by(Category.level, Category.sort_order)
            )
            if content_type:
                query = query.where(Category.type == content_type)

            result = await session.execute(query)
            categories = result.scalars().all()

            return self._build_category_tree(categories)

    async def list_tags_admin(
        self,
        tag_type: Optional[TagType] = None
    ) -> List[Dict[str, Any]]:
        """获取标签列表（管理端，包含停用记录）"""
        async with self.session_factory() as session:
            query = select(Tag).order_by(Tag.type, Tag.sort_order)

            if tag_type:
                query = query.where(Tag.type == tag_type)

            result = await session.execute(query)
            tags = result.scalars().all()

            return [t.to_dict() for t in tags]

    async def list_artists_admin(
        self,
        artist_type: Optional[ArtistType] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取艺术家列表（管理端，包含停用记录）"""
        async with self.session_factory() as session:
            conditions = []

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

            where_clause = and_(*conditions) if conditions else True

            count_query = select(func.count()).select_from(Artist).where(where_clause)
            result = await session.execute(count_query)
            total = result.scalar()

            query = (
                select(Artist)
                .where(where_clause)
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

    # ========================================
    # Admin CRUD
    # ========================================

    async def list_contents(
        self,
        content_type: Optional[ContentType] = None,
        category_id: Optional[int] = None,
        artist_id: Optional[int] = None,
        tag_ids: Optional[List[int]] = None,
        keyword: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取内容列表 (带分页)"""
        async with self.session_factory() as session:
            conditions = []

            if content_type:
                conditions.append(Content.type == content_type)
            if category_id:
                conditions.append(Content.category_id == category_id)
            if keyword:
                conditions.append(
                    or_(
                        Content.title.contains(keyword),
                        Content.title_pinyin.contains(keyword)
                    )
                )
            if is_active is not None:
                conditions.append(Content.is_active == is_active)

            # 基础查询
            query = (
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
            )

            # 艺术家过滤
            if artist_id:
                query = query.join(ContentArtist).where(ContentArtist.artist_id == artist_id)

            # 标签过滤
            if tag_ids:
                query = query.join(ContentTag).where(ContentTag.tag_id.in_(tag_ids))

            if conditions:
                query = query.where(and_(*conditions))

            # 计算总数
            count_query = select(func.count(func.distinct(Content.id))).select_from(Content)
            if artist_id:
                count_query = count_query.join(ContentArtist).where(ContentArtist.artist_id == artist_id)
            if tag_ids:
                count_query = count_query.join(ContentTag).where(ContentTag.tag_id.in_(tag_ids))
            if conditions:
                count_query = count_query.where(and_(*conditions))

            result = await session.execute(count_query)
            total = result.scalar()

            # 分页
            query = (
                query
                .distinct()
                .order_by(Content.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )

            result = await session.execute(query)
            contents = result.scalars().unique().all()

            return {
                "items": [await self._content_to_admin_dict(c) for c in contents],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }

    async def create_content(
        self,
        content_type: ContentType,
        category_id: int,
        title: str,
        minio_path: str,
        title_pinyin: Optional[str] = None,
        subtitle: Optional[str] = None,
        description: Optional[str] = None,
        cover_path: Optional[str] = None,
        duration: int = 0,
        age_min: int = 0,
        age_max: int = 12,
        artist_ids: Optional[List[Dict[str, Any]]] = None,
        tag_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """创建内容"""
        async with self.session_factory() as session:
            content = Content(
                type=content_type,
                category_id=category_id,
                title=title,
                title_pinyin=title_pinyin,
                subtitle=subtitle,
                description=description,
                minio_path=minio_path,
                cover_path=cover_path,
                duration=duration,
                age_min=age_min,
                age_max=age_max
            )
            session.add(content)
            await session.flush()

            # 添加艺术家关联
            if artist_ids:
                for artist_data in artist_ids:
                    ca = ContentArtist(
                        content_id=content.id,
                        artist_id=artist_data["id"],
                        role=ArtistRole(artist_data.get("role", "singer")),
                        is_primary=artist_data.get("is_primary", False)
                    )
                    session.add(ca)

            # 添加标签关联
            if tag_ids:
                for tag_id in tag_ids:
                    ct = ContentTag(content_id=content.id, tag_id=tag_id)
                    session.add(ct)

            await session.commit()
            await session.refresh(content)

            logger.info(f"创建内容: id={content.id}, title={title}")

            # 重新加载关系
            result = await session.execute(
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(Content.id == content.id)
            )
            content = result.scalar_one()

            return await self._content_to_admin_dict(content)

    async def update_content(
        self,
        content_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """更新内容"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(Content.id == content_id)
            )
            content = result.scalar_one_or_none()

            if not content:
                return None

            # 更新基本字段
            for key, value in update_data.items():
                if key not in ("artist_ids", "tag_ids") and hasattr(content, key):
                    setattr(content, key, value)

            # 更新标签关联
            if "tag_ids" in update_data:
                # 删除旧标签
                for ct in list(content.content_tags):
                    await session.delete(ct)
                # 添加新标签
                tag_ids = update_data["tag_ids"] or []
                for tag_id in tag_ids:
                    ct = ContentTag(content_id=content.id, tag_id=tag_id)
                    session.add(ct)

            # 更新艺术家关联
            if "artist_ids" in update_data:
                # 删除旧关联
                for ca in list(content.content_artists):
                    await session.delete(ca)
                # 添加新关联
                artist_ids = update_data["artist_ids"] or []
                for artist_data in artist_ids:
                    ca = ContentArtist(
                        content_id=content.id,
                        artist_id=artist_data["id"],
                        role=ArtistRole(artist_data.get("role", "singer")),
                        is_primary=artist_data.get("is_primary", False)
                    )
                    session.add(ca)

            await session.commit()

            # 重新加载关系
            result = await session.execute(
                select(Content)
                .options(
                    selectinload(Content.category),
                    selectinload(Content.content_artists).selectinload(ContentArtist.artist),
                    selectinload(Content.content_tags).selectinload(ContentTag.tag)
                )
                .where(Content.id == content_id)
            )
            content = result.scalar_one()

            # 清除缓存
            if self.redis:
                await self.redis.invalidate_content_cache(
                    content_id,
                    content.type.value,
                    content.category_id
                )

            logger.info(f"更新内容: id={content_id}")
            return await self._content_to_admin_dict(content)

    async def delete_content(
        self,
        content_id: int,
        hard: bool = False
    ) -> bool:
        """删除内容"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Content).where(Content.id == content_id)
            )
            content = result.scalar_one_or_none()

            if not content:
                return False

            content_type = content.type.value
            category_id = content.category_id

            if hard:
                await session.delete(content)
                logger.info(f"物理删除内容: id={content_id}")
            else:
                content.is_active = False
                logger.info(f"软删除内容: id={content_id}")

            await session.commit()

            # 清除缓存
            if self.redis:
                await self.redis.invalidate_content_cache(
                    content_id, content_type, category_id
                )

            return True

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        async with self.session_factory() as session:
            # 总内容数
            result = await session.execute(
                select(func.count()).select_from(Content)
            )
            total_contents = result.scalar()

            # 各类型数量
            type_counts = {}
            for ct in ContentType:
                result = await session.execute(
                    select(func.count()).select_from(Content).where(Content.type == ct)
                )
                type_counts[ct.value] = result.scalar()

            # 单词总数
            result = await session.execute(
                select(func.count()).select_from(EnglishWord)
            )
            total_words = result.scalar()

            # 艺术家数量
            result = await session.execute(
                select(func.count()).select_from(Artist)
            )
            total_artists = result.scalar()

            # 分类数量
            result = await session.execute(
                select(func.count()).select_from(Category)
            )
            total_categories = result.scalar()

            # 标签数量
            result = await session.execute(
                select(func.count()).select_from(Tag)
            )
            total_tags = result.scalar()

            return {
                "total_contents": total_contents,
                "story_count": type_counts.get("story", 0),
                "music_count": type_counts.get("music", 0),
                "english_count": type_counts.get("english", 0),
                "word_count": total_words,
                "artist_count": total_artists,
                "category_count": total_categories,
                "tag_count": total_tags,
            }

    # ========================================
    # Admin Word CRUD (简化版)
    # ========================================

    async def list_words(
        self,
        level: Optional[str] = None,
        category_id: Optional[int] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取单词列表"""
        async with self.session_factory() as session:
            conditions = []

            if level:
                try:
                    conditions.append(EnglishWord.level == WordLevel(level))
                except ValueError:
                    pass
            if category_id:
                conditions.append(EnglishWord.category_id == category_id)
            if keyword:
                conditions.append(
                    or_(
                        EnglishWord.word.contains(keyword),
                        EnglishWord.translation.contains(keyword)
                    )
                )

            count_query = select(func.count()).select_from(EnglishWord)
            if conditions:
                count_query = count_query.where(and_(*conditions))
            result = await session.execute(count_query)
            total = result.scalar()

            query = select(EnglishWord).options(selectinload(EnglishWord.category))
            if conditions:
                query = query.where(and_(*conditions))
            query = query.order_by(EnglishWord.created_at.desc())
            query = query.offset((page - 1) * page_size).limit(page_size)

            result = await session.execute(query)
            words = result.scalars().all()

            return {
                "items": [await self._word_to_dict(w) for w in words],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }

    async def get_word_by_id(self, word_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取单词"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(EnglishWord)
                .options(selectinload(EnglishWord.category))
                .where(EnglishWord.id == word_id)
            )
            word = result.scalar_one_or_none()

            if word:
                return await self._word_to_dict(word)
            return None

    async def create_word(
        self,
        word: str,
        translation: str,
        phonetic_us: str = "",
        phonetic_uk: str = "",
        audio_us_path: str = "",
        audio_uk_path: str = "",
        level: str = "basic",
        category_id: Optional[int] = None,
        example_sentence: str = "",
        example_translation: str = ""
    ) -> Dict[str, Any]:
        """创建单词"""
        async with self.session_factory() as session:
            word_obj = EnglishWord(
                word=word.lower(),
                phonetic_us=phonetic_us or None,
                phonetic_uk=phonetic_uk or None,
                translation=translation,
                audio_us_path=audio_us_path or None,
                audio_uk_path=audio_uk_path or None,
                level=WordLevel(level),
                category_id=category_id,
                example_sentence=example_sentence or None,
                example_translation=example_translation or None
            )
            session.add(word_obj)
            await session.commit()
            await session.refresh(word_obj)

            logger.info(f"创建单词: id={word_obj.id}, word={word}")
            return await self._word_to_dict(word_obj)

    async def update_word(
        self,
        word_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """更新单词"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(EnglishWord).where(EnglishWord.id == word_id)
            )
            word = result.scalar_one_or_none()

            if not word:
                return None

            for key, value in update_data.items():
                if hasattr(word, key):
                    if key == "level" and isinstance(value, str):
                        value = WordLevel(value)
                    setattr(word, key, value)

            await session.commit()
            await session.refresh(word)

            logger.info(f"更新单词: id={word_id}")
            return await self._word_to_dict(word)

    async def delete_word(self, word_id: int) -> bool:
        """删除单词"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(EnglishWord).where(EnglishWord.id == word_id)
            )
            word = result.scalar_one_or_none()

            if not word:
                return False

            await session.delete(word)
            await session.commit()

            logger.info(f"删除单词: id={word_id}")
            return True

    # ========================================
    # Admin Category CRUD
    # ========================================

    async def create_category(
        self,
        name: str,
        content_type: ContentType,
        parent_id: Optional[int] = None,
        description: str = "",
        icon: str = "",
        sort_order: int = 0
    ) -> Dict[str, Any]:
        """创建分类"""
        async with self.session_factory() as session:
            # 计算层级和路径
            level = 1
            path = ""
            if parent_id:
                parent = await session.execute(
                    select(Category).where(Category.id == parent_id)
                )
                parent_cat = parent.scalar_one_or_none()
                if parent_cat:
                    level = parent_cat.level + 1
                    path = f"{parent_cat.path}/{parent_cat.id}" if parent_cat.path else str(parent_cat.id)

            category = Category(
                name=name,
                type=content_type,
                parent_id=parent_id,
                level=level,
                path=path,
                description=description or None,
                icon=icon or None,
                sort_order=sort_order
            )
            session.add(category)
            await session.commit()
            await session.refresh(category)

            logger.info(f"创建分类: id={category.id}, name={name}")
            return category.to_dict()

    async def update_category(
        self,
        category_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """更新分类"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Category).where(Category.id == category_id)
            )
            category = result.scalar_one_or_none()

            if not category:
                return None

            for key, value in update_data.items():
                if hasattr(category, key):
                    setattr(category, key, value)

            await session.commit()
            await session.refresh(category)

            # 清除缓存
            if self.redis:
                await self.redis.invalidate_category_cache(category.type.value)

            logger.info(f"更新分类: id={category_id}")
            return category.to_dict()

    async def delete_category(self, category_id: int) -> bool:
        """删除分类（软删除）"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Category).where(Category.id == category_id)
            )
            category = result.scalar_one_or_none()

            if not category:
                return False

            category.is_active = False
            await session.commit()

            # 清除缓存
            if self.redis:
                await self.redis.invalidate_category_cache(category.type.value)

            logger.info(f"删除分类: id={category_id}")
            return True

    # ========================================
    # Admin Artist CRUD
    # ========================================

    async def create_artist(
        self,
        name: str,
        artist_type: ArtistType,
        avatar: str = "",
        description: str = ""
    ) -> Dict[str, Any]:
        """创建艺术家"""
        async with self.session_factory() as session:
            artist = Artist(
                name=name,
                type=artist_type,
                avatar_path=avatar or None,
                description=description or None
            )
            session.add(artist)
            await session.commit()
            await session.refresh(artist)

            logger.info(f"创建艺术家: id={artist.id}, name={name}")
            return artist.to_dict()

    async def update_artist(
        self,
        artist_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """更新艺术家"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Artist).where(Artist.id == artist_id)
            )
            artist = result.scalar_one_or_none()

            if not artist:
                return None

            # Schema field → DB column mapping
            field_mapping = {"avatar": "avatar_path"}

            for key, value in update_data.items():
                db_key = field_mapping.get(key, key)
                if db_key == "type" and isinstance(value, str):
                    value = ArtistType(value)
                if hasattr(artist, db_key):
                    setattr(artist, db_key, value)

            await session.commit()
            await session.refresh(artist)

            # 清除缓存
            if self.redis:
                await self.redis.delete_artist_cache(artist_id)

            logger.info(f"更新艺术家: id={artist_id}")
            return artist.to_dict()

    async def delete_artist(self, artist_id: int) -> bool:
        """删除艺术家（软删除）"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Artist).where(Artist.id == artist_id)
            )
            artist = result.scalar_one_or_none()

            if not artist:
                return False

            artist.is_active = False
            await session.commit()

            # 清除缓存
            if self.redis:
                await self.redis.delete_artist_cache(artist_id)

            logger.info(f"删除艺术家: id={artist_id}")
            return True

    # ========================================
    # Admin Tag CRUD
    # ========================================

    async def create_tag(
        self,
        name: str,
        tag_type: TagType,
        color: str = "",
        sort_order: int = 0
    ) -> Dict[str, Any]:
        """创建标签"""
        async with self.session_factory() as session:
            tag = Tag(
                name=name,
                type=tag_type,
                color=color or None,
                sort_order=sort_order
            )
            session.add(tag)
            await session.commit()
            await session.refresh(tag)

            logger.info(f"创建标签: id={tag.id}, name={name}")
            return tag.to_dict()

    async def update_tag(
        self,
        tag_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """更新标签"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Tag).where(Tag.id == tag_id)
            )
            tag = result.scalar_one_or_none()

            if not tag:
                return None

            for key, value in update_data.items():
                if hasattr(tag, key):
                    setattr(tag, key, value)

            await session.commit()
            await session.refresh(tag)

            # 清除缓存: invalidate tag list for this type
            if self.redis and tag.type:
                key = f"tag:list:{tag.type.value}"
                await self.redis.delete(key)

            logger.info(f"更新标签: id={tag_id}")
            return tag.to_dict()

    async def delete_tag(self, tag_id: int) -> bool:
        """删除标签（软删除）"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Tag).where(Tag.id == tag_id)
            )
            tag = result.scalar_one_or_none()

            if not tag:
                return False

            tag.is_active = False
            await session.commit()

            # 清除缓存: invalidate tag list for this type
            if self.redis and tag.type:
                key = f"tag:list:{tag.type.value}"
                await self.redis.delete(key)

            logger.info(f"删除标签: id={tag_id}")
            return True
