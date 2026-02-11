"""
英语学习 Mixin

包含单词查询、随机单词、单词 CRUD
"""

import logging
import random
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from ...models.database import EnglishWord, Category, WordLevel

logger = logging.getLogger(__name__)


class EnglishMixin:
    """英语学习"""

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
            result["audio_us_url"] = self.minio.get_public_url(word.audio_us_path)
        if word.audio_uk_path:
            result["audio_uk_url"] = self.minio.get_public_url(word.audio_uk_path)

        return result

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
