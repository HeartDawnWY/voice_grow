"""
播放历史与统计 Mixin

包含播放记录、历史查询、统计信息
"""

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from ...models.database import (
    Content, ContentType, EnglishWord, PlayHistory,
    Category, Artist, Tag
)

logger = logging.getLogger(__name__)


class PlaybackMixin:
    """播放历史与统计"""

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

        # 更新 Redis 播放历史和热门内容（非关键操作）
        if self.redis:
            try:
                await self.redis.add_to_history(device_id, content_id)
                await self.redis.increment_play_count(content_type.value, content_id)
            except Exception as e:
                logger.warning(f"更新Redis播放历史失败: {e}")

    async def get_recent_history(
        self,
        device_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """获取最近播放历史"""
        # 尝试从 Redis 获取
        if self.redis:
            try:
                content_ids = await self.redis.get_device_history(device_id, limit)
                if content_ids:
                    results = []
                    for cid in content_ids:
                        content = await self.get_content_by_id(cid)
                        if content:
                            results.append(content)
                    return results
            except Exception as e:
                logger.warning(f"从Redis获取播放历史失败，回退DB: {e}")

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

                # 清除缓存（非关键操作，失败不影响主流程）
                if self.redis:
                    try:
                        await self.redis.delete_content(content_id)
                    except Exception as e:
                        logger.warning(f"清除内容缓存失败(content_id={content_id}): {e}")

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
