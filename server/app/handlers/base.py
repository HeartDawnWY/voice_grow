"""
处理器基类和响应数据类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from ..core.nlu import NLUResult
from ..core.tts import TTSService
from ..services.content_service import ContentService


@dataclass
class HandlerResponse:
    """处理器响应"""
    # 响应文本 (用于 TTS)
    text: str

    # 播放 URL (可选，用于播放音频内容)
    play_url: Optional[str] = None

    # 内容信息 (可选)
    content_info: Optional[Dict[str, Any]] = None

    # 是否需要继续监听
    continue_listening: bool = False

    # 额外命令
    commands: List[str] = None

    def __post_init__(self):
        if self.commands is None:
            self.commands = []


class BaseHandler(ABC):
    """处理器基类"""

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService
    ):
        self.content_service = content_service
        self.tts_service = tts_service

    @abstractmethod
    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理意图"""
        pass
