"""
内容管理服务

管理故事、音乐、英语等内容的检索和播放
"""

import logging
import random
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.database import Content, ContentType, EnglishWord, PlayHistory
from .minio_service import MinIOService

logger = logging.getLogger(__name__)


class ContentService:
    """
    内容管理服务

    负责内容检索、播放 URL 生成、播放历史记录等
    """

    def __init__(
        self,
        session_factory,
        minio_service: MinIOService
    ):
        """
        初始化内容服务

        Args:
            session_factory: SQLAlchemy 异步会话工厂
            minio_service: MinIO 服务实例
        """
        self.session_factory = session_factory
        self.minio = minio_service

    async def get_content_by_id(
        self,
        content_id: int,
        include_inactive: bool = False,
        admin_view: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取内容

        Args:
            content_id: 内容 ID
            include_inactive: 是否包含已禁用内容 (管理后台用)
            admin_view: 是否返回管理视图 (包含更多字段)

        Returns:
            内容信息字典，包含播放 URL
        """
        async with self.session_factory() as session:
            query = select(Content).where(Content.id == content_id)
            if not include_inactive:
                query = query.where(Content.is_active == True)

            result = await session.execute(query)
            content = result.scalar_one_or_none()

            if content:
                if admin_view:
                    return await self._content_to_admin_dict(content)
                return await self._content_to_dict(content)

            return None

    async def get_random_story(
        self,
        category: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取随机故事

        Args:
            category: 故事分类 (bedtime, fairy_tale, etc.)

        Returns:
            故事信息
        """
        return await self._get_random_content(ContentType.STORY, category)

    async def get_random_music(
        self,
        category: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取随机音乐

        Args:
            category: 音乐分类 (nursery_rhyme, lullaby, etc.)

        Returns:
            音乐信息
        """
        return await self._get_random_content(ContentType.MUSIC, category)

    async def search_content(
        self,
        content_type: ContentType,
        keyword: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        搜索内容

        Args:
            content_type: 内容类型
            keyword: 搜索关键词
            limit: 返回数量限制

        Returns:
            内容列表
        """
        async with self.session_factory() as session:
            query = select(Content).where(
                and_(
                    Content.type == content_type,
                    Content.is_active == True,
                    Content.title.contains(keyword)
                )
            ).limit(limit)

            result = await session.execute(query)
            contents = result.scalars().all()

            return [await self._content_to_dict(c) for c in contents]

    async def get_content_by_name(
        self,
        content_type: ContentType,
        name: str
    ) -> Optional[Dict[str, Any]]:
        """
        根据名称获取内容

        Args:
            content_type: 内容类型
            name: 内容名称

        Returns:
            内容信息
        """
        async with self.session_factory() as session:
            # 先尝试精确匹配
            result = await session.execute(
                select(Content).where(
                    and_(
                        Content.type == content_type,
                        Content.is_active == True,
                        Content.title == name
                    )
                )
            )
            content = result.scalar_one_or_none()

            # 如果没有精确匹配，尝试模糊匹配
            if not content:
                result = await session.execute(
                    select(Content).where(
                        and_(
                            Content.type == content_type,
                            Content.is_active == True,
                            Content.title.contains(name)
                        )
                    ).limit(1)
                )
                content = result.scalar_one_or_none()

            if content:
                return await self._content_to_dict(content)

            return None

    async def _get_random_content(
        self,
        content_type: ContentType,
        category: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取随机内容"""
        async with self.session_factory() as session:
            # 构建查询条件
            conditions = [
                Content.type == content_type,
                Content.is_active == True
            ]
            if category:
                conditions.append(Content.category == category)

            # 获取符合条件的内容数量
            count_query = select(func.count()).select_from(Content).where(
                and_(*conditions)
            )
            result = await session.execute(count_query)
            count = result.scalar()

            if count == 0:
                logger.warning(f"没有找到内容: type={content_type}, category={category}")
                return None

            # 随机选择
            offset = random.randint(0, count - 1)
            query = select(Content).where(
                and_(*conditions)
            ).offset(offset).limit(1)

            result = await session.execute(query)
            content = result.scalar_one_or_none()

            if content:
                return await self._content_to_dict(content)

            return None

    async def _content_to_dict(self, content: Content) -> Dict[str, Any]:
        """转换内容为字典，并生成播放 URL"""
        play_url = await self.minio.get_presigned_url(content.minio_path)

        return {
            "id": content.id,
            "type": content.type.value,
            "category": content.category,
            "title": content.title,
            "description": content.description,
            "play_url": play_url,
            "minio_path": content.minio_path,
            "duration": content.duration,
            "tags": content.tags.split(",") if content.tags else [],
        }

    # ========== 英语学习 ==========

    async def get_random_word(
        self,
        level: Optional[str] = None,
        category: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取随机单词

        Args:
            level: 级别 (basic, elementary, intermediate)
            category: 分类 (animal, food, color, etc.)

        Returns:
            单词信息
        """
        async with self.session_factory() as session:
            conditions = []
            if level:
                conditions.append(EnglishWord.level == level)
            if category:
                conditions.append(EnglishWord.category == category)

            # 获取数量
            count_query = select(func.count()).select_from(EnglishWord)
            if conditions:
                count_query = count_query.where(and_(*conditions))
            result = await session.execute(count_query)
            count = result.scalar()

            if count == 0:
                return None

            # 随机选择
            offset = random.randint(0, count - 1)
            query = select(EnglishWord)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.offset(offset).limit(1)

            result = await session.execute(query)
            word = result.scalar_one_or_none()

            if word:
                return await self._word_to_dict(word)

            return None

    async def get_word(self, word: str) -> Optional[Dict[str, Any]]:
        """
        获取单词信息

        Args:
            word: 单词

        Returns:
            单词信息
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(EnglishWord).where(EnglishWord.word == word.lower())
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
            "phonetic": word.phonetic,
            "translation": word.translation,
            "level": word.level,
            "category": word.category,
            "example": word.example_sentence,
            "example_translation": word.example_translation,
        }

        # 生成发音 URL
        if word.audio_us_path:
            result["audio_us_url"] = await self.minio.get_presigned_url(word.audio_us_path)
        if word.audio_uk_path:
            result["audio_uk_url"] = await self.minio.get_presigned_url(word.audio_uk_path)

        return result

    # ========== 播放历史 ==========

    async def record_play(
        self,
        device_id: str,
        content_id: int,
        duration_played: Optional[int] = None,
        completed: bool = False
    ):
        """
        记录播放历史

        Args:
            device_id: 设备 ID
            content_id: 内容 ID
            duration_played: 播放时长 (秒)
            completed: 是否播放完成
        """
        async with self.session_factory() as session:
            history = PlayHistory(
                device_id=device_id,
                content_id=content_id,
                duration_played=duration_played,
                completed=completed
            )
            session.add(history)
            await session.commit()

            logger.debug(f"记录播放历史: device={device_id}, content={content_id}")

    async def get_recent_history(
        self,
        device_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取最近播放历史

        Args:
            device_id: 设备 ID
            limit: 返回数量

        Returns:
            播放历史列表
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(PlayHistory)
                .where(PlayHistory.device_id == device_id)
                .order_by(PlayHistory.played_at.desc())
                .limit(limit)
            )
            histories = result.scalars().all()

            return [
                {
                    "content_id": h.content_id,
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

    # ========== Admin Content CRUD ==========

    async def list_contents(
        self,
        content_type: Optional[ContentType] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        获取内容列表 (带分页)

        Args:
            content_type: 内容类型
            category: 分类
            keyword: 搜索关键词
            is_active: 是否激活
            page: 页码
            page_size: 每页数量

        Returns:
            内容列表和分页信息
        """
        async with self.session_factory() as session:
            conditions = []

            if content_type:
                conditions.append(Content.type == content_type)
            if category:
                conditions.append(Content.category == category)
            if keyword:
                conditions.append(Content.title.contains(keyword))
            if is_active is not None:
                conditions.append(Content.is_active == is_active)

            # 计算总数
            count_query = select(func.count()).select_from(Content)
            if conditions:
                count_query = count_query.where(and_(*conditions))
            result = await session.execute(count_query)
            total = result.scalar()

            # 查询列表
            query = select(Content)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.order_by(Content.created_at.desc())
            query = query.offset((page - 1) * page_size).limit(page_size)

            result = await session.execute(query)
            contents = result.scalars().all()

            return {
                "items": [await self._content_to_admin_dict(c) for c in contents],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }

    async def _content_to_admin_dict(self, content: Content) -> Dict[str, Any]:
        """转换内容为管理字典 (包含更多字段)"""
        result = {
            "id": content.id,
            "type": content.type.value,
            "category": content.category,
            "title": content.title,
            "description": content.description,
            "minio_path": content.minio_path,
            "cover_path": content.cover_path,
            "duration": content.duration,
            "file_size": content.file_size,
            "format": content.format,
            "tags": content.tags,
            "age_min": content.age_min,
            "age_max": content.age_max,
            "play_count": content.play_count,
            "like_count": content.like_count,
            "is_active": content.is_active,
            "created_at": content.created_at.isoformat() if content.created_at else None,
            "updated_at": content.updated_at.isoformat() if content.updated_at else None,
        }

        # 生成播放 URL (如果有路径)
        if content.minio_path:
            try:
                result["play_url"] = await self.minio.get_presigned_url(content.minio_path)
            except Exception:
                result["play_url"] = None

        if content.cover_path:
            try:
                result["cover_url"] = await self.minio.get_presigned_url(content.cover_path)
            except Exception:
                result["cover_url"] = None

        return result

    async def create_content(
        self,
        type: ContentType,
        title: str,
        category: str = "",
        description: str = "",
        minio_path: str = "",
        cover_path: str = "",
        duration: int = 0,
        tags: str = "",
        age_min: int = 0,
        age_max: int = 12
    ) -> Dict[str, Any]:
        """
        创建内容

        Args:
            type: 内容类型
            title: 标题
            category: 分类
            description: 描述
            minio_path: MinIO 路径
            cover_path: 封面路径
            duration: 时长
            tags: 标签
            age_min: 最小年龄
            age_max: 最大年龄

        Returns:
            创建的内容
        """
        async with self.session_factory() as session:
            content = Content(
                type=type,
                title=title,
                category=category,
                description=description,
                minio_path=minio_path,
                cover_path=cover_path,
                duration=duration,
                tags=tags,
                age_min=age_min,
                age_max=age_max
            )
            session.add(content)
            await session.commit()
            await session.refresh(content)

            logger.info(f"创建内容: id={content.id}, title={title}")
            return await self._content_to_admin_dict(content)

    async def update_content(
        self,
        content_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        更新内容

        Args:
            content_id: 内容 ID
            update_data: 更新数据

        Returns:
            更新后的内容
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(Content).where(Content.id == content_id)
            )
            content = result.scalar_one_or_none()

            if not content:
                return None

            for key, value in update_data.items():
                if hasattr(content, key):
                    setattr(content, key, value)

            await session.commit()
            await session.refresh(content)

            logger.info(f"更新内容: id={content_id}")
            return await self._content_to_admin_dict(content)

    async def delete_content(
        self,
        content_id: int,
        hard: bool = False
    ) -> bool:
        """
        删除内容

        Args:
            content_id: 内容 ID
            hard: 是否物理删除

        Returns:
            是否成功
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(Content).where(Content.id == content_id)
            )
            content = result.scalar_one_or_none()

            if not content:
                return False

            if hard:
                await session.delete(content)
                logger.info(f"物理删除内容: id={content_id}")
            else:
                content.is_active = False
                logger.info(f"软删除内容: id={content_id}")

            await session.commit()
            return True

    async def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计数据
        """
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

            return {
                "total_contents": total_contents,
                "story_count": type_counts.get("story", 0),
                "music_count": type_counts.get("music", 0),
                "english_count": type_counts.get("english", 0),
                "word_count": total_words
            }

    # ========== Admin Word CRUD ==========

    async def list_words(
        self,
        level: Optional[str] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """
        获取单词列表 (带分页)

        Args:
            level: 级别
            category: 分类
            keyword: 搜索关键词
            page: 页码
            page_size: 每页数量

        Returns:
            单词列表和分页信息
        """
        async with self.session_factory() as session:
            conditions = []

            if level:
                conditions.append(EnglishWord.level == level)
            if category:
                conditions.append(EnglishWord.category == category)
            if keyword:
                conditions.append(
                    (EnglishWord.word.contains(keyword)) |
                    (EnglishWord.translation.contains(keyword))
                )

            # 计算总数
            count_query = select(func.count()).select_from(EnglishWord)
            if conditions:
                count_query = count_query.where(and_(*conditions))
            result = await session.execute(count_query)
            total = result.scalar()

            # 查询列表
            query = select(EnglishWord)
            if conditions:
                query = query.where(and_(*conditions))
            query = query.order_by(EnglishWord.created_at.desc())
            query = query.offset((page - 1) * page_size).limit(page_size)

            result = await session.execute(query)
            words = result.scalars().all()

            return {
                "items": [await self._word_to_admin_dict(w) for w in words],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size
            }

    async def _word_to_admin_dict(self, word: EnglishWord) -> Dict[str, Any]:
        """转换单词为管理字典"""
        result = {
            "id": word.id,
            "word": word.word,
            "phonetic": word.phonetic,
            "translation": word.translation,
            "audio_us_path": word.audio_us_path,
            "audio_uk_path": word.audio_uk_path,
            "level": word.level,
            "category": word.category,
            "example_sentence": word.example_sentence,
            "example_translation": word.example_translation,
            "created_at": word.created_at.isoformat() if word.created_at else None,
        }

        # 生成音频 URL
        if word.audio_us_path:
            try:
                result["audio_us_url"] = await self.minio.get_presigned_url(word.audio_us_path)
            except Exception:
                result["audio_us_url"] = None

        if word.audio_uk_path:
            try:
                result["audio_uk_url"] = await self.minio.get_presigned_url(word.audio_uk_path)
            except Exception:
                result["audio_uk_url"] = None

        return result

    async def create_word(
        self,
        word: str,
        translation: str,
        phonetic: str = "",
        audio_us_path: str = "",
        audio_uk_path: str = "",
        level: str = "basic",
        category: str = "",
        example_sentence: str = "",
        example_translation: str = ""
    ) -> Dict[str, Any]:
        """
        创建单词

        Args:
            word: 单词
            translation: 翻译
            phonetic: 音标
            audio_us_path: 美式发音路径
            audio_uk_path: 英式发音路径
            level: 级别
            category: 分类
            example_sentence: 例句
            example_translation: 例句翻译

        Returns:
            创建的单词
        """
        async with self.session_factory() as session:
            word_obj = EnglishWord(
                word=word.lower(),
                phonetic=phonetic,
                translation=translation,
                audio_us_path=audio_us_path or None,
                audio_uk_path=audio_uk_path or None,
                level=level,
                category=category or None,
                example_sentence=example_sentence or None,
                example_translation=example_translation or None
            )
            session.add(word_obj)
            await session.commit()
            await session.refresh(word_obj)

            logger.info(f"创建单词: id={word_obj.id}, word={word}")
            return await self._word_to_admin_dict(word_obj)

    async def get_word_by_id(self, word_id: int) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取单词

        Args:
            word_id: 单词 ID

        Returns:
            单词信息
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(EnglishWord).where(EnglishWord.id == word_id)
            )
            word = result.scalar_one_or_none()

            if word:
                return await self._word_to_admin_dict(word)

            return None

    async def update_word(
        self,
        word_id: int,
        update_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        更新单词

        Args:
            word_id: 单词 ID
            update_data: 更新数据

        Returns:
            更新后的单词
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(EnglishWord).where(EnglishWord.id == word_id)
            )
            word = result.scalar_one_or_none()

            if not word:
                return None

            for key, value in update_data.items():
                if hasattr(word, key):
                    setattr(word, key, value)

            await session.commit()
            await session.refresh(word)

            logger.info(f"更新单词: id={word_id}")
            return await self._word_to_admin_dict(word)

    async def delete_word(self, word_id: int) -> bool:
        """
        删除单词

        Args:
            word_id: 单词 ID

        Returns:
            是否成功
        """
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
