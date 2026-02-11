"""
处理器路由注册

根据意图分发到相应的处理器
"""

import logging
from typing import Optional, Dict

from ..core.nlu import Intent, NLUResult
from ..core.tts import TTSService
from ..core.llm import LLMService
from ..services.content_service import ContentService
from ..services.session_service import SessionService
from .base import HandlerResponse
from .story import StoryHandler
from .music import MusicHandler
from .english import EnglishHandler
from .chat import ChatHandler
from .control import ControlHandler
from .system import SystemHandler
from .delete import DeleteHandler

logger = logging.getLogger(__name__)


class HandlerRouter:
    """
    处理器路由

    根据意图分发到相应的处理器
    """

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService,
        llm_service: LLMService,
        session_service: Optional[SessionService] = None,
        play_queue_service=None,
    ):
        # 初始化各处理器
        self.story_handler = StoryHandler(content_service, tts_service, llm_service, play_queue_service)
        self.music_handler = MusicHandler(content_service, tts_service, play_queue_service)
        self.english_handler = EnglishHandler(content_service, tts_service)
        self.chat_handler = ChatHandler(content_service, tts_service, llm_service, session_service)
        self.control_handler = ControlHandler(content_service, tts_service, play_queue_service)
        self.system_handler = SystemHandler(content_service, tts_service)
        self.delete_handler = DeleteHandler(content_service, tts_service)

        # 意图到处理器的映射
        self._intent_map = {
            # 故事
            Intent.PLAY_STORY: self.story_handler,
            Intent.PLAY_STORY_CATEGORY: self.story_handler,
            Intent.PLAY_STORY_BY_NAME: self.story_handler,

            # 音乐
            Intent.PLAY_MUSIC: self.music_handler,
            Intent.PLAY_MUSIC_CATEGORY: self.music_handler,
            Intent.PLAY_MUSIC_BY_NAME: self.music_handler,
            Intent.PLAY_MUSIC_BY_ARTIST: self.music_handler,

            # 播放控制
            Intent.CONTROL_PAUSE: self.control_handler,
            Intent.CONTROL_RESUME: self.control_handler,
            Intent.CONTROL_STOP: self.control_handler,
            Intent.CONTROL_NEXT: self.control_handler,
            Intent.CONTROL_PREVIOUS: self.control_handler,
            Intent.CONTROL_VOLUME_UP: self.control_handler,
            Intent.CONTROL_VOLUME_DOWN: self.control_handler,
            Intent.CONTROL_PLAY_MODE: self.control_handler,

            # 英语学习
            Intent.ENGLISH_LEARN: self.english_handler,
            Intent.ENGLISH_WORD: self.english_handler,
            Intent.ENGLISH_FOLLOW: self.english_handler,

            # 对话
            Intent.CHAT: self.chat_handler,

            # 内容管理
            Intent.DELETE_CONTENT: self.delete_handler,

            # 系统
            Intent.SYSTEM_TIME: self.system_handler,
            Intent.SYSTEM_WEATHER: self.system_handler,
        }

        # 处理器名称映射（供 pipeline pending_action 查找）
        self._handler_name_map = {
            "delete": self.delete_handler,
        }

    async def route(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """路由到相应处理器"""
        intent = nlu_result.intent

        handler = self._intent_map.get(intent)
        if handler:
            logger.info(f"路由: {intent.value} -> {handler.__class__.__name__}")
            return await handler.handle(nlu_result, device_id, context)

        # 默认使用对话处理器
        logger.warning(f"未知意图: {intent.value}, 使用对话处理器")
        return await self.chat_handler.handle(nlu_result, device_id, context)

    def get_handler_by_name(self, name: str):
        """根据名称获取处理器（供 pipeline pending_action 确认流程使用）"""
        return self._handler_name_map.get(name)
