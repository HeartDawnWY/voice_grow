"""
对话处理器
"""

import logging
from typing import Optional, Dict

from ..core.nlu import NLUResult
from ..core.tts import TTSService
from ..core.llm import LLMService, ChatMessage
from ..services.content_service import ContentService
from ..services.session_service import SessionService
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)


class ChatHandler(BaseHandler):
    """对话处理器"""

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService,
        llm_service: LLMService,
        session_service: Optional[SessionService] = None
    ):
        super().__init__(content_service, tts_service)
        self.llm_service = llm_service
        self.session_service = session_service

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理对话意图"""
        user_message = nlu_result.raw_text

        # 从 Redis 获取对话历史
        history = []
        if self.session_service:
            history_data = await self.session_service.get_conversation_context(device_id, limit=10)
            history = [ChatMessage(role=msg["role"], content=msg["content"]) for msg in history_data]

        # 调用 LLM
        response = await self.llm_service.chat(user_message, history)

        # 保存对话到 Redis
        if self.session_service:
            await self.session_service.add_to_conversation(device_id, "user", user_message)
            await self.session_service.add_to_conversation(device_id, "assistant", response)

        return HandlerResponse(text=response)

    async def clear_history(self, device_id: str):
        """清除对话历史"""
        if self.session_service:
            await self.session_service.clear_conversation(device_id)
