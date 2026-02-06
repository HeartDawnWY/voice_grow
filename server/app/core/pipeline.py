"""
语音处理流水线

完整的语音交互流程:
唤醒 -> 录音 -> ASR -> NLU -> Handler -> TTS -> 播放
"""

import logging
from typing import Optional, TYPE_CHECKING

from .asr import ASRService
from .nlu import NLUService
from .tts import TTSService

if TYPE_CHECKING:
    from ..api.websocket import DeviceConnection

logger = logging.getLogger(__name__)


class VoicePipeline:
    """
    语音处理流水线

    完整的语音交互流程:
    唤醒 -> 录音 -> ASR -> NLU -> Handler -> TTS -> 播放
    """

    def __init__(
        self,
        asr_service: ASRService,
        nlu_service: NLUService,
        tts_service: TTSService,
        handler_router,
        play_queue_service=None,
        content_service=None,
    ):
        self.asr = asr_service
        self.nlu = nlu_service
        self.tts = tts_service
        self.router = handler_router
        self.play_queue_service = play_queue_service
        self.content_service = content_service

    async def process_text(
        self,
        text: str,
        device_id: str,
        conn: "DeviceConnection"
    ):
        """
        处理文本输入（跳过 ASR，直接走 NLU → Handler → 响应）

        用于 open-xiaoai instruction 事件：设备端云 ASR 已完成识别，
        服务端直接从文本开始处理。

        Args:
            text: 识别文本
            device_id: 设备 ID
            conn: 设备连接
        """
        from ..handlers import HandlerResponse

        try:
            logger.info(f"处理文本输入: '{text}' (device={device_id})")

            # 1. NLU 意图识别
            nlu_result = await self.nlu.recognize(text)
            logger.info(f"NLU 识别结果: {nlu_result}")

            # 2. Handler 处理
            response = await self.router.route(nlu_result, device_id)
            logger.info(f"Handler 响应: {response.text[:50]}...")

            # 3. 执行响应
            await self.respond(conn, response)

        except Exception as e:
            logger.error(f"文本处理失败: {e}", exc_info=True)
            try:
                error_response = HandlerResponse(text="抱歉，出了点问题，请稍后再试")
                await self.respond(conn, error_response)
            except Exception:
                pass

    async def process_audio(
        self,
        audio_data: bytes,
        device_id: str,
        conn: "DeviceConnection"
    ):
        """
        处理音频数据

        Args:
            audio_data: PCM 音频数据
            device_id: 设备 ID
            conn: 设备连接

        Returns:
            处理结果 (HandlerResponse)
        """
        from ..handlers import HandlerResponse

        try:
            # 1. ASR 语音识别
            logger.info(f"开始 ASR 识别，音频大小: {len(audio_data)} bytes")
            text = await self.asr.transcribe(audio_data)

            if not text or len(text.strip()) == 0:
                logger.warning("ASR 识别结果为空")
                return HandlerResponse(text="抱歉，我没有听清楚，请再说一遍")

            logger.info(f"ASR 识别结果: {text}")

            # 2. NLU 意图识别
            nlu_result = await self.nlu.recognize(text)
            logger.info(f"NLU 识别结果: {nlu_result}")

            # 3. Handler 处理
            response = await self.router.route(nlu_result, device_id)
            logger.info(f"Handler 响应: {response.text[:50]}...")

            return response

        except Exception as e:
            logger.error(f"语音处理失败: {e}", exc_info=True)
            return HandlerResponse(text="抱歉，出了点问题，请稍后再试")

    async def respond(
        self,
        conn: "DeviceConnection",
        response
    ):
        """
        执行响应

        Args:
            conn: 设备连接
            response: 处理器响应
        """
        from ..api.websocket import manager
        from ..models.protocol import Request

        try:
            # 0. 停止小米云端正在播放的内容
            #    abort_xiaoai 中断对话，pause 停止音乐播放器
            #    注意: stop_recording 由 on_audio_complete() 负责，此处不重复发送
            await manager.send_request(conn.device_id, Request.abort_xiaoai())
            await manager.send_request(conn.device_id, Request.pause())

            # 1. 如果有播放 URL，直接播放
            if response.play_url:
                # 先播放提示语
                if response.text:
                    tts_url = await self.tts.synthesize_to_url(response.text)
                    await manager.send_request(
                        conn.device_id,
                        Request.play_url(tts_url, block=True)
                    )

                # 播放内容
                await manager.send_request(
                    conn.device_id,
                    Request.play_url(response.play_url)
                )
            else:
                # 只有文本响应，使用 TTS
                tts_url = await self.tts.synthesize_to_url(response.text)
                await manager.send_request(
                    conn.device_id,
                    Request.play_url(tts_url)
                )

            # 2. 执行额外命令
            for command in response.commands:
                if command == "pause":
                    await manager.send_request(conn.device_id, Request.pause())
                elif command == "play":
                    await manager.send_request(conn.device_id, Request.play())
                elif command == "volume_up":
                    await manager.send_request(conn.device_id, Request.volume_up())
                elif command == "volume_down":
                    await manager.send_request(conn.device_id, Request.volume_down())
                elif command == "next":
                    await self._play_queue_track(conn, "next")
                elif command == "previous":
                    await self._play_queue_track(conn, "previous")

            # 3. 如果需要继续监听，唤醒设备
            if response.continue_listening:
                await manager.send_request(
                    conn.device_id,
                    Request.wake_up(silent=True)
                )

        except Exception as e:
            logger.error(f"响应执行失败: {e}", exc_info=True)

    async def _play_queue_track(self, conn: "DeviceConnection", direction: str):
        """播放队列中的上一首/下一首"""
        from ..api.websocket import manager
        from ..models.protocol import Request

        if not self.play_queue_service:
            logger.warning(f"{direction}: play_queue_service 未配置")
            return

        if direction == "next":
            content_id = await self.play_queue_service.get_next(conn.device_id)
        else:
            content_id = await self.play_queue_service.get_previous(conn.device_id)

        if content_id is None:
            logger.info(f"{direction}: 队列中没有更多内容")
            tts_url = await self.tts.synthesize_to_url("没有更多内容了")
            await manager.send_request(conn.device_id, Request.play_url(tts_url))
            return

        if self.content_service:
            content = await self.content_service.get_content_by_id(content_id)
            if content and content.get("play_url"):
                logger.info(f"{direction}: 播放内容 id={content_id}")
                await manager.send_request(
                    conn.device_id,
                    Request.play_url(content["play_url"])
                )
                return

        logger.warning(f"{direction}: 内容 id={content_id} 未找到或无播放链接")
