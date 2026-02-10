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
        super().__init__(content_service, tts_service, play_queue_service)

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

        # 上一首/下一首：直接从队列获取并返回 play_url
        if intent in (Intent.CONTROL_NEXT, Intent.CONTROL_PREVIOUS):
            return await self._handle_queue_navigate(intent, device_id)

        # 暂停：respond() 的 abort+pause 已足够停止播放
        #   走标准路径 → abort+pause 停歌 → TTS → _queue_active 自动清除
        if intent == Intent.CONTROL_PAUSE:
            return HandlerResponse(text="已暂停")

        # 停止：同暂停，但额外清空队列
        if intent == Intent.CONTROL_STOP:
            return await self._handle_stop(device_id)

        # 继续播放：skip_interrupt 避免打断暂停状态，直接发 play 恢复
        if intent == Intent.CONTROL_RESUME:
            return await self._handle_resume(device_id)

        # 音量调节：skip_interrupt 不中断音乐，直接调音量
        #   附带 play 命令确保 instruction 路径（预先 pause 了）也能恢复播放
        if intent in (Intent.CONTROL_VOLUME_UP, Intent.CONTROL_VOLUME_DOWN):
            cmd = "volume_up" if intent == Intent.CONTROL_VOLUME_UP else "volume_down"
            return HandlerResponse(
                text="",
                skip_interrupt=True,
                commands=[cmd, "play"],
            )

        return HandlerResponse(text="好的")

    async def _handle_queue_navigate(
        self,
        intent: Intent,
        device_id: str
    ) -> HandlerResponse:
        """处理上一首/下一首，自动跳过不可用内容"""
        if not self.play_queue_service:
            return HandlerResponse(text="播放队列功能暂不可用")

        queue = await self.play_queue_service.get_queue(device_id)
        if not queue:
            return HandlerResponse(text="没有播放队列")

        # 尝试找到可用内容（跳过无 play_url 的）
        max_skip = len(queue)
        for _ in range(max_skip):
            if intent == Intent.CONTROL_NEXT:
                content_id = await self.play_queue_service.get_next(device_id, wrap=True)
            else:
                content_id = await self.play_queue_service.get_previous(device_id, wrap=True)

            if content_id is None:
                break

            content = await self.content_service.get_content_by_id(content_id)
            if content and content.get("play_url"):
                await self.content_service.increment_play_count(content_id)
                direction = "下一个" if intent == Intent.CONTROL_NEXT else "上一个"
                return HandlerResponse(
                    text=f"好的，{direction}，{content['title']}",
                    play_url=content["play_url"],
                    content_info=content,
                    queue_active=True,
                )

            logger.warning(f"队列内容不可用，跳过: id={content_id}")

        return HandlerResponse(text="队列中没有可播放的内容")

    async def _handle_stop(self, device_id: str) -> HandlerResponse:
        """处理停止：清空队列 + 标准 abort+pause 路径"""
        if self.play_queue_service:
            await self.play_queue_service.clear_queue(device_id)
        return HandlerResponse(text="已停止")

    async def _handle_resume(self, device_id: str) -> HandlerResponse:
        """处理继续播放

        skip_interrupt=True: 不发 abort+pause，保留媒体播放器暂停状态
        text="": 不播 TTS（play_url 会覆盖媒体播放器状态，导致 play 恢复 TTS 而非原歌曲）
        commands=["play"]: 直接恢复媒体播放器
        queue_active: 如果队列有内容则恢复自动续播
        """
        has_queue = False
        if self.play_queue_service:
            queue = await self.play_queue_service.get_queue(device_id)
            has_queue = len(queue) > 0

        return HandlerResponse(
            text="",
            skip_interrupt=True,
            commands=["play"],
            queue_active=True if has_queue else None,
        )

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

        # 如果队列有内容，恢复 queue_active（abort+pause 会清除它）
        # 这样 TTS 播完后 auto_play_next 会以新模式继续播放
        has_queue = False
        if self.play_queue_service:
            queue = await self.play_queue_service.get_queue(device_id)
            has_queue = len(queue) > 0

        return HandlerResponse(
            text=f"已切换到{mode_names[mode]}模式",
            queue_active=True if has_queue else None,
        )
