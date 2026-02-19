"""
对话处理器
"""

import logging
import re
from typing import Optional, Dict

from ..core.nlu import NLUResult
from ..core.tts import TTSService
from ..core.llm import LLMService, ChatMessage
from ..services.content_service import ContentService
from ..services.session_service import SessionService
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)

# 告别关键词 — 匹配时结束连续对话（允许 ASR 附带的尾部标点）
_FAREWELL_PATTERN = re.compile(
    r'^(再见|拜拜|不聊了|不说了|不想聊了|晚安|bye|886|88|结束对话|退出)[。！!.~？?，,]*$',
    re.IGNORECASE
)


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

        # 检测告别意图 — 短路回复，跳过 LLM 并清空历史
        if _FAREWELL_PATTERN.search(user_message.strip()):
            logger.info(f"检测到告别意图: '{user_message}' (device={device_id})")
            await self.clear_history(device_id)
            return HandlerResponse(text="再见！下次再聊哦！", continue_listening=False)

        # 从 Redis 获取对话历史（Redis 异常时降级为无历史模式）
        history = []
        if self.session_service:
            try:
                history_data = await self.session_service.get_conversation_context(device_id, limit=10)
                history = [ChatMessage(role=msg["role"], content=msg["content"]) for msg in history_data]
            except Exception as e:
                logger.warning(f"获取对话历史失败，降级为无历史模式: {e}")

        # 调用 LLM
        response = await self.llm_service.chat(user_message, history)

        # 保存对话到 Redis（失败不影响响应）
        if self.session_service:
            try:
                await self.session_service.add_to_conversation(device_id, "user", user_message)
                await self.session_service.add_to_conversation(device_id, "assistant", response)
            except Exception as e:
                logger.warning(f"保存对话历史失败: {e}")

        return HandlerResponse(
            text=response,
            continue_listening=True,
        )

    async def clear_history(self, device_id: str):
        """清除对话历史"""
        if self.session_service:
            try:
                await self.session_service.clear_conversation(device_id)
            except Exception as e:
                logger.warning(f"清除对话历史失败: {e}")
