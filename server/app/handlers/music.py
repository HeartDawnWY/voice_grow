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

        if intent == Intent.PLAY_MUSIC:
            content = await self.content_service.get_random_music()

        elif intent == Intent.PLAY_MUSIC_CATEGORY:
            category = slots.get("category")
            content = await self.content_service.get_random_music(category)

        elif intent == Intent.PLAY_MUSIC_BY_NAME:
            name = slots.get("music_name")
            if name:
                content = await self.content_service.get_content_by_name(
                    ContentType.MUSIC, name
                )

        if content:
            await self.content_service.increment_play_count(content["id"])

            return HandlerResponse(
                text=f"为你播放{content['title']}",
                play_url=content["play_url"],
                content_info=content
            )
        else:
            return HandlerResponse(
                text="抱歉，没有找到你想听的歌，换一首试试吧"
            )
