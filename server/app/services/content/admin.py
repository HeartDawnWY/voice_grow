"""
管理后台 Mixin

包含内容/分类/艺术家/标签的 Admin CRUD 操作
"""

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ...models.database import (
    Content, ContentType, Category, Artist, Tag,
    ContentArtist, ContentTag, ArtistType, ArtistRole, TagType
)

logger = logging.getLogger(__name__)


class AdminMixin:
    """管理后台 CRUD"""

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
    # Admin Content CRUD
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

            # 同步写入向量 DB（非关键，失败不影响主流程）
            if self.vector and self.vector.is_ready:
                try:
                    await self.vector.add_content(
                        content_id=content.id,
                        title=content.title,
                        content_type=content.type.value,
                    )
                except Exception as e:
                    logger.warning(f"向量写入失败（非关键）: content_id={content.id}, error={e}")

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

            # 清除缓存（非关键操作）
            if self.redis:
                try:
                    await self.redis.invalidate_content_cache(
                        content_id,
                        content.type.value,
                        content.category_id
                    )
                except Exception as e:
                    logger.warning(f"清除内容缓存失败(id={content_id}): {e}")

            # 同步更新向量 DB（标题可能变更）
            if self.vector and self.vector.is_ready and content:
                try:
                    await self.vector.add_content(
                        content_id=content.id,
                        title=content.title,
                        content_type=content.type.value,
                    )
                except Exception as e:
                    logger.warning(f"向量更新失败（非关键）: content_id={content.id}, error={e}")

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

            # 清除缓存（非关键操作）
            if self.redis:
                try:
                    await self.redis.invalidate_content_cache(
                        content_id, content_type, category_id
                    )
                except Exception as e:
                    logger.warning(f"清除内容缓存失败(id={content_id}): {e}")

            # 从向量 DB 删除（内容停用）
            if self.vector and self.vector.is_ready:
                try:
                    self.vector.delete_content(content_id)
                except Exception as e:
                    logger.warning(f"向量删除失败（非关键）: content_id={content_id}, error={e}")

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

            # 清除缓存（非关键操作）
            if self.redis:
                try:
                    await self.redis.invalidate_category_cache(category.type.value)
                except Exception as e:
                    logger.warning(f"清除分类缓存失败: {e}")

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

            # 清除缓存（非关键操作）
            if self.redis:
                try:
                    await self.redis.invalidate_category_cache(category.type.value)
                except Exception as e:
                    logger.warning(f"清除分类缓存失败: {e}")

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

            # Schema field -> DB column mapping
            field_mapping = {"avatar": "avatar_path"}

            for key, value in update_data.items():
                db_key = field_mapping.get(key, key)
                if db_key == "type" and isinstance(value, str):
                    value = ArtistType(value)
                if hasattr(artist, db_key):
                    setattr(artist, db_key, value)

            await session.commit()
            await session.refresh(artist)

            # 清除缓存（非关键操作）
            if self.redis:
                try:
                    await self.redis.delete_artist_cache(artist_id)
                except Exception as e:
                    logger.warning(f"清除艺术家缓存失败(id={artist_id}): {e}")

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

            # 清除缓存（非关键操作）
            if self.redis:
                try:
                    await self.redis.delete_artist_cache(artist_id)
                except Exception as e:
                    logger.warning(f"清除艺术家缓存失败(id={artist_id}): {e}")

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

            # 清除缓存（非关键操作）
            if self.redis and tag.type:
                try:
                    key = f"tag:list:{tag.type.value}"
                    await self.redis.delete(key)
                except Exception as e:
                    logger.warning(f"清除标签缓存失败: {e}")

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

            # 清除缓存（非关键操作）
            if self.redis and tag.type:
                try:
                    key = f"tag:list:{tag.type.value}"
                    await self.redis.delete(key)
                except Exception as e:
                    logger.warning(f"清除标签缓存失败: {e}")

            logger.info(f"删除标签: id={tag_id}")
            return True
