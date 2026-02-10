"""
音乐播放处理器
"""

import logging
from typing import Optional, Dict

from ..core.nlu import Intent, NLUResult
from ..models.database import ContentType
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)


class MusicHandler(BaseHandler):
    """音乐播放处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理音乐相关意图"""
        intent = nlu_result.intent
        slots = nlu_result.slots

        content = None
        queued_count = 0  # 入队歌曲数

        if intent == Intent.PLAY_MUSIC:
            content = await self.content_service.get_random_music()

        elif intent == Intent.PLAY_MUSIC_CATEGORY:
            category = slots.get("category")
            content = await self.content_service.get_random_music(category)

        elif intent == Intent.PLAY_MUSIC_BY_ARTIST:
            artist_name = slots.get("artist_name")
            if artist_name:
                results = await self.content_service.search_by_artist(
                    artist_name, ContentType.MUSIC, limit=20
                )
                if results:
                    content = results[0]
                    # 将所有结果加入播放队列
                    if self.play_queue_service and len(results) > 1:
                        content_ids = [r["id"] for r in results]
                        await self.play_queue_service.set_queue(device_id, content_ids, start_index=0)
                        queued_count = len(results)

        elif intent == Intent.PLAY_MUSIC_BY_NAME:
            music_name = slots.get("music_name")
            artist_name = slots.get("artist_name")
            if artist_name and music_name:
                content = await self.content_service.search_by_artist_and_title(
                    artist_name, music_name
                )
            elif music_name:
                content = await self.content_service.get_content_by_name(
                    ContentType.MUSIC, music_name
                )

        if content:
            await self.content_service.increment_play_count(content["id"])

            # 单曲播放时清空旧队列，避免"下一首"跳到陈旧队列
            if self.play_queue_service and queued_count == 0:
                await self.play_queue_service.clear_queue(device_id)

            # 构建响应文本
            if queued_count > 1:
                artist_name = slots.get("artist_name", "")
                response_text = f"找到{artist_name}的{queued_count}首歌，先为你播放{content['title']}"
            else:
                response_text = f"为你播放{content['title']}"

            return HandlerResponse(
                text=response_text,
                play_url=content["play_url"],
                content_info=content,
                queue_active=queued_count > 1,
            )
        else:
            artist = slots.get("artist_name", "")
            music = slots.get("music_name", "")
            hint = f"{artist}的{music}" if artist and music else artist or music or "这首歌"
            return HandlerResponse(
                text=f"抱歉，没有找到{hint}，换一首试试吧"
            )
