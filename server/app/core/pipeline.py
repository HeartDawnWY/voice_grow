"""
语音处理流水线

完整的语音交互流程:
唤醒 -> 录音 -> ASR -> NLU -> Handler -> TTS -> 播放
"""

import asyncio
import logging
from typing import Optional, Dict, TYPE_CHECKING

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

    def _build_handler_context(self, conn: "DeviceConnection") -> Dict:
        """构建 handler 上下文（play_tts, play_url, set_pending_action）"""
        async def _play_tts(text):
            from ..api.websocket import manager
            from ..models.protocol import Request
            url = await self.tts.synthesize_to_url(text)
            await manager.send_request(conn.device_id, Request.play_url(url))

        async def _play_url(url):
            from ..api.websocket import manager
            from ..models.protocol import Request
            await manager.send_request(conn.device_id, Request.play_url(url))

        def _set_pending_action(action_type, data, handler_name, timeout=30.0):
            from ..api.websocket import PendingAction
            conn.pending_action = PendingAction(
                action_type=action_type,
                data=data,
                handler_name=handler_name,
                timeout=timeout,
            )

        return {"play_tts": _play_tts, "play_url": _play_url, "set_pending_action": _set_pending_action}

    async def _handle_pending_action(self, conn: "DeviceConnection", text: str, device_id: str = None):
        """
        检查并处理待确认操作，返回 response 或 None（走正常流程）
        """
        if conn.pending_action is not None:
            pending = conn.pending_action
            conn.pending_action = None  # 消费掉
            if not pending.is_expired():
                handler = self.router.get_handler_by_name(pending.handler_name)
                if handler and hasattr(handler, "handle_confirmation"):
                    logger.info(f"拦截待确认操作: {pending.action_type} (handler={pending.handler_name})")
                    return await handler.handle_confirmation(
                        text, pending.data, device_id, context=None
                    )
                else:
                    logger.warning(f"待确认操作的处理器未找到或缺少 handle_confirmation: {pending.handler_name}")
            else:
                logger.info(f"待确认操作已过期，走正常 NLU 流程")
        return None

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

            # 0. 检查待确认操作（多轮对话拦截）
            pending_response = await self._handle_pending_action(conn, text, device_id)
            if pending_response is not None:
                await self.respond(conn, pending_response)
                return

            # 1. NLU 意图识别
            nlu_result = await self.nlu.recognize(text)
            logger.info(f"NLU 识别结果: {nlu_result}")

            # 2. Handler 处理（传递中间播放回调给 handler）
            context = self._build_handler_context(conn)
            response = await self.router.route(nlu_result, device_id, context)
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

            # 1.5. 检查待确认操作（多轮对话拦截）
            #       注意: process_audio 返回 response 由 on_audio_complete() 调用 respond()
            pending_response = await self._handle_pending_action(conn, text, device_id)
            if pending_response is not None:
                return pending_response

            # 2. NLU 意图识别
            nlu_result = await self.nlu.recognize(text)
            logger.info(f"NLU 识别结果: {nlu_result}")

            # 3. Handler 处理（传递中间播放回调给 handler）
            context = self._build_handler_context(conn)
            response = await self.router.route(nlu_result, device_id, context)
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
            # 0. 预合成 TTS（在中断播放之前完成，减少静音间隔）
            tts_url = None
            if response.text:
                tts_url = await self.tts.synthesize_to_url(response.text)

            # 1. 中断云端和媒体播放器（可通过 skip_interrupt 跳过）
            #    skip_interrupt 用于音量调节、继续播放等不应中断当前播放的场景
            if not response.skip_interrupt:
                await manager.send_request(conn.device_id, Request.abort_xiaoai())
                await manager.send_request(conn.device_id, Request.pause())
                # 中断播放 = 队列自动续播默认关闭（除非 handler 显式恢复）
                conn._queue_active = False

            # 2. 播放内容或 TTS
            if response.play_url:
                # 先播放提示语，等待播完后再播内容（音箱是替换式播放）
                if tts_url:
                    await manager.send_request(
                        conn.device_id,
                        Request.play_url(tts_url)
                    )
                    wait_seconds = len(response.text) * 0.25 + 0.5
                    await asyncio.sleep(wait_seconds)

                # 播放内容
                await manager.send_request(
                    conn.device_id,
                    Request.play_url(response.play_url)
                )
            elif tts_url:
                # 只有文本响应，使用 TTS
                await manager.send_request(
                    conn.device_id,
                    Request.play_url(tts_url)
                )

            # 3. 执行额外命令
            for command in response.commands:
                if command == "pause":
                    await manager.send_request(conn.device_id, Request.pause())
                elif command == "play":
                    await manager.send_request(conn.device_id, Request.play())
                elif command == "volume_up":
                    await manager.send_request(conn.device_id, Request.volume_up())
                elif command == "volume_down":
                    await manager.send_request(conn.device_id, Request.volume_down())

            # 4. 显式更新队列活跃状态
            #    True=启用, False=关闭, None=不改变（保持 step 1 的默认值）
            if response.queue_active is not None:
                conn._queue_active = response.queue_active

            # 5. 如果需要继续监听，唤醒设备
            if response.continue_listening:
                await manager.send_request(
                    conn.device_id,
                    Request.wake_up(silent=True)
                )

        except Exception as e:
            logger.error(f"响应执行失败: {e}", exc_info=True)
