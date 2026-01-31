"""
英语学习处理器
"""

import logging
from typing import Optional, Dict

from ..core.nlu import Intent, NLUResult
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)


class EnglishHandler(BaseHandler):
    """英语学习处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理英语学习相关意图"""
        intent = nlu_result.intent
        slots = nlu_result.slots

        if intent == Intent.ENGLISH_LEARN:
            word_info = await self.content_service.get_random_word(level="basic")
            if word_info:
                return await self._build_word_response(word_info)
            else:
                return HandlerResponse(text="英语学习功能暂时不可用，稍后再试吧")

        elif intent == Intent.ENGLISH_WORD:
            word = slots.get("word", "")
            word_info = await self.content_service.get_word(word)
            if word_info:
                return await self._build_word_response(word_info)
            else:
                return HandlerResponse(
                    text=f"抱歉，我不知道{word}用英语怎么说"
                )

        elif intent == Intent.ENGLISH_FOLLOW:
            word = slots.get("word", "")
            return HandlerResponse(
                text=f"请跟我读：{word}",
                continue_listening=True
            )

        return HandlerResponse(text="我们来学英语吧！")

    async def _build_word_response(self, word_info: Dict) -> HandlerResponse:
        """构建单词响应"""
        word = word_info["word"]
        translation = word_info["translation"]
        phonetic = word_info.get("phonetic_us") or word_info.get("phonetic_uk") or ""

        text = f"{translation}的英语是{word}"
        if phonetic:
            text += f"，读作{phonetic}"

        audio_url = word_info.get("audio_us_url")

        return HandlerResponse(
            text=text,
            play_url=audio_url,
            content_info=word_info
        )
