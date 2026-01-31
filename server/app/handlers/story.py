"""
故事播放处理器
"""

import logging
from typing import Optional, Dict

from ..core.nlu import Intent, NLUResult
from ..models.database import ContentType
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)


class StoryHandler(BaseHandler):
    """故事播放处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理故事相关意图"""
        intent = nlu_result.intent
        slots = nlu_result.slots

        content = None

        if intent == Intent.PLAY_STORY:
            content = await self.content_service.get_random_story()

        elif intent == Intent.PLAY_STORY_CATEGORY:
            category = slots.get("category")
            content = await self.content_service.get_random_story(category)

        elif intent == Intent.PLAY_STORY_BY_NAME:
            name = slots.get("story_name")
            if name:
                content = await self.content_service.get_content_by_name(
                    ContentType.STORY, name
                )

        if content:
            await self.content_service.increment_play_count(content["id"])

            return HandlerResponse(
                text=f"好的，给你讲{content['title']}",
                play_url=content["play_url"],
                content_info=content
            )
        else:
            return HandlerResponse(
                text="抱歉，没有找到你想听的故事，换一个试试吧"
            )
