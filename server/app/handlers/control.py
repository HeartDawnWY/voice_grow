"""
播放控制处理器
"""

import logging
from typing import Optional, Dict

from ..core.nlu import Intent, NLUResult
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)


class ControlHandler(BaseHandler):
    """播放控制处理器"""

    def __init__(self, content_service, tts_service, play_queue_service=None):
        super().__init__(content_service, tts_service)
        self.play_queue_service = play_queue_service

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理播放控制意图"""
        intent = nlu_result.intent

        # 播放模式控制
        if intent == Intent.CONTROL_PLAY_MODE:
            return await self._handle_play_mode(nlu_result, device_id)

        # 控制命令映射
        command_map = {
            Intent.CONTROL_PAUSE: ("pause", "已暂停"),
            Intent.CONTROL_RESUME: ("play", "继续播放"),
            Intent.CONTROL_STOP: ("pause", "已停止"),
            Intent.CONTROL_NEXT: ("next", "好的，下一个"),
            Intent.CONTROL_PREVIOUS: ("previous", "好的，上一个"),
            Intent.CONTROL_VOLUME_UP: ("volume_up", "好的，大声一点"),
            Intent.CONTROL_VOLUME_DOWN: ("volume_down", "好的，小声一点"),
        }

        if intent in command_map:
            command, text = command_map[intent]
            return HandlerResponse(
                text=text,
                commands=[command]
            )

        return HandlerResponse(text="好的")

    async def _handle_play_mode(
        self,
        nlu_result: NLUResult,
        device_id: str
    ) -> HandlerResponse:
        """处理播放模式切换"""
        if not self.play_queue_service:
            return HandlerResponse(text="播放模式功能暂不可用")

        mode_text = nlu_result.slots.get("play_mode", "")

        from ..services.play_queue_service import PlayMode

        mode_mapping = {
            "单曲循环": PlayMode.SINGLE_LOOP,
            "列表循环": PlayMode.PLAYLIST_LOOP,
            "随机播放": PlayMode.SHUFFLE,
            "顺序播放": PlayMode.SEQUENTIAL,
        }

        mode = mode_mapping.get(mode_text)
        if not mode:
            return HandlerResponse(text="不支持的播放模式")

        await self.play_queue_service.set_mode(device_id, mode)

        mode_names = {
            PlayMode.SEQUENTIAL: "顺序播放",
            PlayMode.SINGLE_LOOP: "单曲循环",
            PlayMode.PLAYLIST_LOOP: "列表循环",
            PlayMode.SHUFFLE: "随机播放",
        }

        return HandlerResponse(text=f"已切换到{mode_names[mode]}模式")
