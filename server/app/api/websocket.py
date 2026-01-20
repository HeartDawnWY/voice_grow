"""
WebSocket API - open-xiaoai 客户端通信

处理与小爱音箱的 WebSocket 连接
端口: 4399
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import get_settings, AudioConfig
from ..models.protocol import (
    Event, Stream, Request, Response,
    ListeningState, PlayingState,
    parse_json_message
)
from ..core.asr import ASRService, AudioBuffer
from ..core.nlu import NLUService
from ..core.tts import TTSService
from ..core.llm import LLMService
from ..services.handlers import HandlerRouter, HandlerResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@dataclass
class DeviceConnection:
    """设备连接状态"""
    device_id: str
    websocket: WebSocket

    # 监听状态机
    state: ListeningState = ListeningState.IDLE

    # 音频缓冲器
    audio_buffer: Optional[AudioBuffer] = None

    # 播放状态
    playing_state: PlayingState = PlayingState.IDLE

    # 当前播放内容
    current_content: Optional[Dict] = None

    # 超时任务
    _timeout_task: Optional[asyncio.Task] = None

    # 待响应的请求
    pending_requests: Dict[str, asyncio.Future] = field(default_factory=dict)

    def __post_init__(self):
        if self.audio_buffer is None:
            settings = get_settings()
            self.audio_buffer = AudioBuffer(
                sample_rate=settings.audio.sample_rate,
                sample_width=settings.audio.sample_width,
                channels=settings.audio.channels,
                silence_threshold=settings.audio.silence_threshold,
                max_duration=settings.audio.max_duration,
                min_duration=settings.audio.min_duration,
            )


class ConnectionManager:
    """
    WebSocket 连接管理器

    管理所有设备连接
    """

    def __init__(self):
        self.connections: Dict[str, DeviceConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, device_id: str) -> DeviceConnection:
        """建立连接"""
        await websocket.accept()

        async with self._lock:
            # 如果已有连接，先断开旧连接
            if device_id in self.connections:
                old_conn = self.connections[device_id]
                try:
                    await old_conn.websocket.close()
                except Exception:
                    pass

            conn = DeviceConnection(device_id=device_id, websocket=websocket)
            self.connections[device_id] = conn

        logger.info(f"设备连接: {device_id}")
        return conn

    async def disconnect(self, device_id: str):
        """断开连接"""
        async with self._lock:
            if device_id in self.connections:
                conn = self.connections.pop(device_id)
                # 取消超时任务
                if conn._timeout_task and not conn._timeout_task.done():
                    conn._timeout_task.cancel()

        logger.info(f"设备断开: {device_id}")

    def get_connection(self, device_id: str) -> Optional[DeviceConnection]:
        """获取连接"""
        return self.connections.get(device_id)

    async def send_request(
        self,
        device_id: str,
        request: Request,
        wait_response: bool = False,
        timeout: float = 10.0
    ) -> Optional[Response]:
        """
        发送请求到设备

        Args:
            device_id: 设备 ID
            request: 请求对象
            wait_response: 是否等待响应
            timeout: 超时时间

        Returns:
            响应对象 (如果 wait_response=True)
        """
        conn = self.get_connection(device_id)
        if not conn:
            logger.warning(f"设备未连接: {device_id}")
            return None

        try:
            await conn.websocket.send_text(request.to_json())
            logger.debug(f"发送请求: {request.command} -> {device_id}")

            if wait_response:
                future = asyncio.get_event_loop().create_future()
                conn.pending_requests[request.id] = future

                try:
                    response = await asyncio.wait_for(future, timeout=timeout)
                    return response
                except asyncio.TimeoutError:
                    logger.warning(f"请求超时: {request.id}")
                    return None
                finally:
                    conn.pending_requests.pop(request.id, None)

        except Exception as e:
            logger.error(f"发送请求失败: {e}")
            return None

    async def broadcast(self, request: Request):
        """广播请求到所有设备"""
        for device_id in list(self.connections.keys()):
            await self.send_request(device_id, request)


# 全局连接管理器
manager = ConnectionManager()


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
        handler_router: HandlerRouter
    ):
        self.asr = asr_service
        self.nlu = nlu_service
        self.tts = tts_service
        self.router = handler_router

    async def process_audio(
        self,
        audio_data: bytes,
        device_id: str,
        conn: DeviceConnection
    ) -> Optional[HandlerResponse]:
        """
        处理音频数据

        Args:
            audio_data: PCM 音频数据
            device_id: 设备 ID
            conn: 设备连接

        Returns:
            处理结果
        """
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
        conn: DeviceConnection,
        response: HandlerResponse
    ):
        """
        执行响应

        Args:
            conn: 设备连接
            response: 处理器响应
        """
        try:
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
                    # TODO: 实现下一个内容播放逻辑
                    logger.info("下一个命令 (暂未实现)")
                elif command == "previous":
                    # TODO: 实现上一个内容播放逻辑
                    logger.info("上一个命令 (暂未实现)")

            # 3. 如果需要继续监听，唤醒设备
            if response.continue_listening:
                await manager.send_request(
                    conn.device_id,
                    Request.wake_up(silent=True)
                )

        except Exception as e:
            logger.error(f"响应执行失败: {e}", exc_info=True)


# 全局服务实例 (在应用启动时初始化)
_pipeline: Optional[VoicePipeline] = None


def get_pipeline() -> VoicePipeline:
    """获取语音流水线实例"""
    global _pipeline
    if _pipeline is None:
        raise RuntimeError("VoicePipeline 未初始化")
    return _pipeline


def set_pipeline(pipeline: VoicePipeline):
    """设置语音流水线实例"""
    global _pipeline
    _pipeline = pipeline


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 端点

    处理来自 open-xiaoai 客户端的连接
    """
    # 生成设备 ID (实际应从客户端获取)
    device_id = str(uuid.uuid4())[:8]

    # 建立连接
    conn = await manager.connect(websocket, device_id)
    settings = get_settings()

    try:
        while True:
            # 接收消息
            message = await websocket.receive()

            if message["type"] == "websocket.receive":
                # 文本消息 (JSON)
                if "text" in message:
                    await handle_text_message(conn, message["text"])

                # 二进制消息 (音频流)
                elif "bytes" in message:
                    await handle_binary_message(conn, message["bytes"])

            elif message["type"] == "websocket.disconnect":
                break

    except WebSocketDisconnect:
        logger.info(f"设备断开连接: {device_id}")
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}", exc_info=True)
    finally:
        await manager.disconnect(device_id)


async def handle_text_message(conn: DeviceConnection, text: str):
    """
    处理文本消息 (JSON)

    消息类型: Event 或 Response
    """
    try:
        message = parse_json_message(text)

        if isinstance(message, Event):
            await handle_event(conn, message)
        elif isinstance(message, Response):
            await handle_response(conn, message)
        else:
            logger.warning(f"未知消息格式: {text[:100]}")

    except Exception as e:
        logger.error(f"处理文本消息失败: {e}", exc_info=True)


async def handle_event(conn: DeviceConnection, event: Event):
    """处理事件"""
    logger.debug(f"收到事件: {event.event}, data={event.data}")

    if event.is_wake_word():
        # 唤醒词事件
        await on_wake_word(conn, event)

    elif event.is_playing_event():
        # 播放状态变化
        state = event.get_playing_state()
        if state:
            conn.playing_state = state
            logger.debug(f"播放状态变化: {state.value}")

    elif event.is_instruction():
        # 客户端 ASR 结果 (在服务端 ASR 模式下仅作参考)
        text = event.get_instruction_text()
        if text:
            logger.debug(f"客户端 ASR 结果 (参考): {text}")


async def handle_response(conn: DeviceConnection, response: Response):
    """处理响应"""
    logger.debug(f"收到响应: id={response.id}, code={response.code}")

    # 完成待处理的请求
    if response.id in conn.pending_requests:
        future = conn.pending_requests[response.id]
        if not future.done():
            future.set_result(response)


async def handle_binary_message(conn: DeviceConnection, data: bytes):
    """
    处理二进制消息 (音频流)
    """
    # 只在监听状态下处理音频
    if conn.state not in [ListeningState.WOKEN, ListeningState.LISTENING]:
        return

    # 如果是 WOKEN 状态，开始录音
    if conn.state == ListeningState.WOKEN:
        conn.state = ListeningState.LISTENING
        conn.audio_buffer.start()
        logger.info(f"开始录音: {conn.device_id}")

        # 取消唤醒超时
        if conn._timeout_task and not conn._timeout_task.done():
            conn._timeout_task.cancel()

    # 追加音频数据
    conn.audio_buffer.append(data)

    # 检查是否应该停止
    if conn.audio_buffer.should_stop():
        await on_audio_complete(conn)


async def on_wake_word(conn: DeviceConnection, event: Event):
    """处理唤醒词事件"""
    logger.info(f"唤醒: {conn.device_id}, wake_word={event.data}")

    # 中断原生小爱
    await manager.send_request(conn.device_id, Request.abort_xiaoai())

    # 进入等待录音状态
    conn.state = ListeningState.WOKEN
    conn.audio_buffer = AudioBuffer()

    # 设置唤醒超时 (如果用户唤醒后不说话)
    settings = get_settings()

    async def wake_timeout():
        await asyncio.sleep(settings.audio.wake_timeout)
        if conn.state == ListeningState.WOKEN:
            logger.info(f"唤醒超时: {conn.device_id}")
            conn.state = ListeningState.IDLE

    conn._timeout_task = asyncio.create_task(wake_timeout())

    # 播放提示音 (可选)
    # await manager.send_request(conn.device_id, Request.play_text("我在", block=True))


async def on_audio_complete(conn: DeviceConnection):
    """处理录音完成"""
    logger.info(f"录音完成: {conn.device_id}")

    # 获取音频数据
    audio_data = conn.audio_buffer.stop()
    conn.state = ListeningState.PROCESSING

    try:
        # 处理语音
        pipeline = get_pipeline()
        response = await pipeline.process_audio(audio_data, conn.device_id, conn)

        # 执行响应
        if response:
            conn.state = ListeningState.RESPONDING
            await pipeline.respond(conn, response)

    except Exception as e:
        logger.error(f"处理录音失败: {e}", exc_info=True)

        # 播放错误提示
        try:
            await manager.send_request(
                conn.device_id,
                Request.play_text("抱歉，出了点问题")
            )
        except Exception:
            pass

    finally:
        # 恢复空闲状态
        conn.state = ListeningState.IDLE
