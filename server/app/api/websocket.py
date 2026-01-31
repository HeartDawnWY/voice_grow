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
from typing import Optional, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import get_settings
from ..models.protocol import (
    Event, Stream, Request, Response,
    ListeningState, PlayingState,
    parse_json_message
)
from ..core.asr import AudioBuffer
from ..handlers import HandlerResponse

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
    """WebSocket 连接管理器"""

    def __init__(self):
        self.connections: Dict[str, DeviceConnection] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, device_id: str) -> DeviceConnection:
        """建立连接"""
        await websocket.accept()

        async with self._lock:
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
        """发送请求到设备"""
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


# 全局流水线实例 (在应用启动时初始化)
_pipeline = None


def get_pipeline():
    """获取语音流水线实例"""
    global _pipeline
    if _pipeline is None:
        raise RuntimeError("VoicePipeline 未初始化")
    return _pipeline


def set_pipeline(pipeline):
    """设置语音流水线实例"""
    global _pipeline
    _pipeline = pipeline


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点"""
    device_id = str(uuid.uuid4())[:8]

    conn = await manager.connect(websocket, device_id)

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.receive":
                if "text" in message:
                    await handle_text_message(conn, message["text"])
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
    """处理文本消息 (JSON)"""
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
        await on_wake_word(conn, event)

    elif event.is_playing_event():
        state = event.get_playing_state()
        if state:
            conn.playing_state = state
            logger.debug(f"播放状态变化: {state.value}")

    elif event.is_instruction():
        text = event.get_instruction_text()
        if text:
            logger.debug(f"客户端 ASR 结果 (参考): {text}")


async def handle_response(conn: DeviceConnection, response: Response):
    """处理响应"""
    logger.debug(f"收到响应: id={response.id}, code={response.code}")

    if response.id in conn.pending_requests:
        future = conn.pending_requests[response.id]
        if not future.done():
            future.set_result(response)


async def handle_binary_message(conn: DeviceConnection, data: bytes):
    """处理二进制消息 (音频流)"""
    if conn.state not in [ListeningState.WOKEN, ListeningState.LISTENING]:
        return

    if conn.state == ListeningState.WOKEN:
        conn.state = ListeningState.LISTENING
        conn.audio_buffer.start()
        logger.info(f"开始录音: {conn.device_id}")

        if conn._timeout_task and not conn._timeout_task.done():
            conn._timeout_task.cancel()

    conn.audio_buffer.append(data)

    if conn.audio_buffer.should_stop():
        await on_audio_complete(conn)


async def on_wake_word(conn: DeviceConnection, event: Event):
    """处理唤醒词事件"""
    logger.info(f"唤醒: {conn.device_id}, wake_word={event.data}")

    await manager.send_request(conn.device_id, Request.abort_xiaoai())

    conn.state = ListeningState.WOKEN

    settings = get_settings()
    conn.audio_buffer = AudioBuffer(
        sample_rate=settings.audio.sample_rate,
        sample_width=settings.audio.sample_width,
        channels=settings.audio.channels,
        silence_threshold=settings.audio.silence_threshold,
        max_duration=settings.audio.max_duration,
        min_duration=settings.audio.min_duration,
    )

    async def wake_timeout():
        await asyncio.sleep(settings.audio.wake_timeout)
        if conn.state == ListeningState.WOKEN:
            logger.info(f"唤醒超时: {conn.device_id}")
            conn.state = ListeningState.IDLE

    conn._timeout_task = asyncio.create_task(wake_timeout())


async def on_audio_complete(conn: DeviceConnection):
    """处理录音完成"""
    logger.info(f"录音完成: {conn.device_id}")

    audio_data = conn.audio_buffer.stop()
    conn.state = ListeningState.PROCESSING

    try:
        pipeline = get_pipeline()
        response = await pipeline.process_audio(audio_data, conn.device_id, conn)

        if response:
            conn.state = ListeningState.RESPONDING
            await pipeline.respond(conn, response)

    except Exception as e:
        logger.error(f"处理录音失败: {e}", exc_info=True)

        try:
            await manager.send_request(
                conn.device_id,
                Request.play_text("抱歉，出了点问题")
            )
        except Exception:
            pass

    finally:
        conn.state = ListeningState.IDLE
