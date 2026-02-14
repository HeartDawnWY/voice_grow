"""
音乐播放处理器
"""

import logging
from typing import Optional, Dict, List, Tuple

from ..core.nlu import Intent, NLUResult
from ..models.database import ContentType
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)


class MusicHandler(BaseHandler):
    """音乐播放处理器"""

    async def _setup_queue(
        self, results: List[Dict], device_id: str
    ) -> Tuple[Optional[Dict], int]:
        """过滤可播放内容并设置播放队列

        Returns:
            (首条内容, 入队数量)
        """
        playable = [r for r in results if r.get("play_url")]
        if not playable:
            return None, 0
        content = playable[0]
        queued_count = 0
        if self.play_queue_service and len(playable) > 1:
            content_ids = [r["id"] for r in playable]
            await self.play_queue_service.set_queue(device_id, content_ids, start_index=0)
            queued_count = len(playable)
        return content, queued_count

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
        queued_count = 0
        category_label = ""

        if intent == Intent.PLAY_MUSIC:
            results = await self.content_service.get_content_list(
                ContentType.MUSIC, limit=30, shuffle=True
            )
            content, queued_count = await self._setup_queue(results, device_id)

        elif intent == Intent.PLAY_MUSIC_CATEGORY:
            category = slots.get("category")
            if not category:
                return HandlerResponse(text="请告诉我你想听什么类型的音乐")
            category_label = category
            results = await self.content_service.get_content_list(
                ContentType.MUSIC, category_name=category, limit=30, shuffle=True
            )
            content, queued_count = await self._setup_queue(results, device_id)

        elif intent == Intent.PLAY_MUSIC_BY_ARTIST:
            artist_name = slots.get("artist_name")
            if artist_name:
                results = await self.content_service.search_by_artist(
                    artist_name, ContentType.MUSIC, limit=20
                )
                if results:
                    content, queued_count = await self._setup_queue(results, device_id)

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

        # 统一保护：确保内容有音频文件
        if content and not content.get("play_url"):
            logger.warning(f"内容无音频文件，跳过: id={content.get('id')}, title={content.get('title')}")
            content = None

        if content:
            await self.content_service.increment_play_count(content["id"])

            # 单曲播放时清空旧队列，避免"下一首"跳到陈旧队列
            if self.play_queue_service and queued_count == 0:
                await self.play_queue_service.clear_queue(device_id)

            # 构建响应文本
            if queued_count > 1:
                if intent == Intent.PLAY_MUSIC_BY_ARTIST:
                    artist_name = slots.get("artist_name", "")
                    response_text = f"找到{artist_name}的{queued_count}首歌，先为你播放{content['title']}"
                elif intent == Intent.PLAY_MUSIC_CATEGORY:
                    response_text = f"为你播放{category_label}，共{queued_count}首，先来一首{content['title']}"
                else:
                    response_text = f"为你随机播放音乐，共{queued_count}首，先来一首{content['title']}"
            else:
                response_text = f"为你播放{content['title']}"

            return HandlerResponse(
                text=response_text,
                play_url=content["play_url"],
                content_info=content,
                queue_active=queued_count > 1,
            )
        else:
            if intent in (Intent.PLAY_MUSIC, Intent.PLAY_MUSIC_CATEGORY):
                hint = f"{category_label}分类" if category_label else "音乐"
                return HandlerResponse(
                    text=f"抱歉，{hint}暂时没有内容，你可以在管理后台添加"
                )
            artist = slots.get("artist_name", "")
            music = slots.get("music_name", "")
            hint = f"{artist}的{music}" if artist and music else artist or music or "这首歌"
            return HandlerResponse(
                text=f"抱歉，没有找到{hint}，换一首试试吧"
            )
