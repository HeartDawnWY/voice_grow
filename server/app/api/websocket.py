"""
WebSocket API - open-xiaoai 客户端通信

处理与小爱音箱的 WebSocket 连接
端口: 4399
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import get_settings
from ..models.protocol import (
    Event, Stream, Request, Response,
    ListeningState, PlayingState,
    parse_json_message, parse_binary_message,
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

    # 指令文本缓冲（open-xiaoai 流式 ASR 去抖）
    _instruction_text: Optional[str] = None
    _instruction_timer: Optional[asyncio.Task] = None
    _instruction_dispatched: bool = False  # 防止 is_stop + is_final 重复触发

    # start_recording 请求 ID（用于异步检测失败）
    _start_recording_id: Optional[str] = None

    # pipeline 处理中标记（用于拦截云端播放命令）
    _pipeline_active: bool = False

    # 播放队列活跃标记（播放完当前曲目后自动播下一首）
    _queue_active: bool = False

    # 自动播放下一首的待执行任务（防止重复触发）
    _auto_play_task: Optional[asyncio.Task] = None

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
                if conn._instruction_timer and not conn._instruction_timer.done():
                    conn._instruction_timer.cancel()

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
            payload_summary = str(request.payload)[:80] if request.payload else ""
            logger.debug(f"发送请求: {request.command}({payload_summary}) -> {device_id}")

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


async def _auto_play_next(conn: DeviceConnection, pipeline):
    """播放队列中的下一首（播放结束后自动触发）"""
    try:
        # 短暂延迟避免 TTS→内容之间的 Idle 事件误触发
        await asyncio.sleep(1.5)
        # 延迟后再检查：如果已经在播放、队列被关闭、或 pipeline 活跃，跳过
        if conn.playing_state == PlayingState.PLAYING or not conn._queue_active or conn._pipeline_active:
            return

        # 尝试获取下一首可用内容（跳过不可用的）
        max_skip = 5
        for _ in range(max_skip):
            content_id = await pipeline.play_queue_service.get_next(conn.device_id)
            if content_id is None:
                logger.info(f"播放队列已结束 (device={conn.device_id})")
                conn._queue_active = False
                return

            if pipeline.content_service:
                content = await pipeline.content_service.get_content_by_id(content_id)
                if content and content.get("play_url"):
                    logger.info(f"自动播放下一首: {content.get('title')} (id={content_id}, device={conn.device_id})")
                    await pipeline.content_service.increment_play_count(content_id)
                    await manager.send_request(
                        conn.device_id,
                        Request.play_url(content["play_url"])
                    )
                    return

            logger.warning(f"队列内容不可用，跳过: id={content_id}")

        logger.warning(f"连续 {max_skip} 首不可用，停止队列 (device={conn.device_id})")
        conn._queue_active = False
    except Exception as e:
        logger.error(f"自动播放下一首失败: {e}", exc_info=True)
        conn._queue_active = False


@router.websocket("/")
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
    logger.info(f"收到事件: {event.event}, data={event.data}")

    if event.is_wake_word():
        await on_wake_word(conn, event)

    elif event.is_playing_event():
        state = event.get_playing_state()
        if state:
            conn.playing_state = state
            logger.debug(f"播放状态变化: {state.value}")

            # 云端抢先播放拦截：pipeline 处理中 + 云端触发 Playing → 立即打断
            if state == PlayingState.PLAYING and conn._pipeline_active:
                logger.info(f"拦截云端抢先播放 (pipeline 活跃中, device={conn.device_id})")
                await manager.send_request(conn.device_id, Request.abort_xiaoai())
                await manager.send_request(conn.device_id, Request.pause())

            # 自动播放下一首：播放结束 + 队列活跃 + pipeline 空闲
            if state == PlayingState.IDLE and conn._queue_active and not conn._pipeline_active:
                # 取消已有的待执行任务，防止重复触发
                if conn._auto_play_task and not conn._auto_play_task.done():
                    conn._auto_play_task.cancel()
                pipeline = get_pipeline()
                if pipeline and pipeline.play_queue_service:
                    conn._auto_play_task = asyncio.create_task(_auto_play_next(conn, pipeline))

    elif event.is_instruction():
        # 如果音频路径已激活（本地录音中），忽略 instruction 事件
        if conn.state in (
            ListeningState.WOKEN, ListeningState.LISTENING, ListeningState.PROCESSING
        ):
            logger.debug(
                f"忽略 instruction 事件 (当前状态={conn.state.value}，音频路径激活)"
            )
            return

        # 云端播放命令拦截：pipeline 处理中收到 AudioPlayer/Play 或 TTS → 立即打断
        if conn._pipeline_active and event.is_cloud_playback_command():
            logger.info(f"拦截云端播放命令 (pipeline 活跃中, device={conn.device_id})")
            await manager.send_request(conn.device_id, Request.abort_xiaoai())
            await manager.send_request(conn.device_id, Request.pause())
            return

        text = event.get_instruction_text()
        if text:
            is_final = event.is_instruction_final()
            logger.info(f"收到指令文本: '{text}' (final={is_final})")
            conn._instruction_text = text

            if is_final and not conn._instruction_dispatched:
                # ASR 最终结果，立即中断小爱并处理（不等去抖）
                conn._instruction_dispatched = True
                if conn._instruction_timer and not conn._instruction_timer.done():
                    conn._instruction_timer.cancel()
                    conn._instruction_timer = None
                # 在 await 之前同步设置！防止 yield 期间 Idle 事件触发 _auto_play_next
                if conn._auto_play_task and not conn._auto_play_task.done():
                    conn._auto_play_task.cancel()
                    conn._auto_play_task = None
                conn._pipeline_active = True
                logger.info(f"ASR final，立即中断小爱并处理")
                await manager.send_request(conn.device_id, Request.abort_xiaoai())
                asyncio.create_task(_on_instruction_complete(conn))
            elif not is_final:
                # 收到新的非 final 事件 = 新一轮 ASR 开始，重置 dispatch 防护
                # 这样新一轮的 final 事件能正常触发 dispatch
                # 同一轮的重复 final 仍然被阻止（中间不会有非 final 事件）
                conn._instruction_dispatched = False
                # 用户开始说话，立即取消自动播放，防止队列指针在用户命令前被推进
                # 场景：歌曲结束 → auto_play 1.5s 后推进队列 → 用户说"上一首" → 指针已偏移
                if conn._auto_play_task and not conn._auto_play_task.done():
                    conn._auto_play_task.cancel()
                    conn._auto_play_task = None
                await _reset_instruction_timer(conn)


async def handle_response(conn: DeviceConnection, response: Response):
    """处理响应"""
    logger.debug(f"收到响应: id={response.id}, code={response.code}")

    # 检测 start_recording 失败 → 降级到 instruction 路径
    if (
        conn._start_recording_id
        and response.id == conn._start_recording_id
    ):
        conn._start_recording_id = None
        if response.is_failure():
            logger.warning(
                f"start_recording 失败 (device={conn.device_id}): {response.msg}，"
                f"降级到 instruction 路径"
            )
            # 回退状态：如果还在 WOKEN（尚未收到音频），重置为 IDLE
            if conn.state == ListeningState.WOKEN:
                conn.state = ListeningState.IDLE
                if conn._timeout_task and not conn._timeout_task.done():
                    conn._timeout_task.cancel()
            return
        else:
            logger.info(f"start_recording 确认成功 (device={conn.device_id})")
            return

    if response.id in conn.pending_requests:
        future = conn.pending_requests[response.id]
        if not future.done():
            future.set_result(response)


async def handle_binary_message(conn: DeviceConnection, data: bytes):
    """处理二进制消息 (音频流)

    open-xiaoai start_recording 模式下，二进制帧为 JSON 编码的 Stream:
      {"id":"...","tag":"record","bytes":[...],"data":null}
    解析 Stream → 提取 PCM 数据。如果 JSON 解析失败，回退为 raw PCM（向后兼容）。
    """
    if conn.state not in [ListeningState.WOKEN, ListeningState.LISTENING]:
        return

    # 尝试解析为 Stream 对象
    stream = parse_binary_message(data)
    if stream and stream.is_audio_stream():
        pcm_data = stream.data
    else:
        # 回退: 直接当作 raw PCM（向后兼容）
        pcm_data = data

    if not pcm_data:
        return

    if conn.state == ListeningState.WOKEN:
        conn.state = ListeningState.LISTENING
        conn.audio_buffer.start()
        logger.info(f"开始录音: {conn.device_id}")

        if conn._timeout_task and not conn._timeout_task.done():
            conn._timeout_task.cancel()

    conn.audio_buffer.append(pcm_data)

    if conn.audio_buffer.should_stop():
        # 立即切换状态防止重复触发，然后在独立 task 中处理
        # （不阻塞 WebSocket 消息循环，使 _pipeline_active 拦截生效）
        conn.state = ListeningState.PROCESSING
        asyncio.create_task(on_audio_complete(conn))


async def _reset_instruction_timer(conn: DeviceConnection):
    """重置指令去抖定时器

    open-xiaoai 的 instruction 是流式的（多个 NewLine 事件），
    每次收到新文本时重置定时器。1.5 秒无新文本则视为最终结果。
    """
    if conn._instruction_timer and not conn._instruction_timer.done():
        conn._instruction_timer.cancel()

    async def _fire():
        await asyncio.sleep(1.5)
        # Guard: 如果已被 is_final 路径触发，跳过（防止重复 dispatch）
        if conn._instruction_dispatched:
            return
        conn._instruction_dispatched = True
        await _on_instruction_complete(conn)

    conn._instruction_timer = asyncio.create_task(_fire())


async def _on_instruction_complete(conn: DeviceConnection):
    """指令去抖完成，处理最终文本"""
    text = conn._instruction_text
    conn._instruction_text = None
    conn._instruction_timer = None
    # 注意: 不重置 _instruction_dispatched — 保持 True 防止同一轮 final 事件重复触发
    # 在下一轮 ASR 的 non-final 事件中重置（见 handle_event elif not is_final 分支）

    if not text or not text.strip():
        conn._pipeline_active = False  # 重置（final 路径提前设置了 True）
        return

    logger.info(f"指令最终文本: '{text}' (device={conn.device_id})")

    # 立即标记 pipeline 活跃 + 取消自动播放（在任何 await 之前！）
    # 防止 await 期间 Idle 事件触发 _auto_play_next 与用户命令竞态
    conn._pipeline_active = True
    if conn._auto_play_task and not conn._auto_play_task.done():
        conn._auto_play_task.cancel()
        conn._auto_play_task = None

    # 中断小爱原生响应 + 暂停音乐播放器
    try:
        await manager.send_request(conn.device_id, Request.abort_xiaoai())
        await manager.send_request(conn.device_id, Request.pause())
        logger.info(f"已中断小爱原生响应并暂停播放 (device={conn.device_id})")
    except Exception as e:
        logger.warning(f"中断小爱失败: {e}")

    try:
        pipeline = get_pipeline()
        await pipeline.process_text(text.strip(), conn.device_id, conn)
    except Exception as e:
        logger.error(f"处理指令文本失败: {e}", exc_info=True)
        try:
            await manager.send_request(
                conn.device_id,
                Request.play_text("抱歉，出了点问题")
            )
        except Exception:
            pass
    finally:
        conn._pipeline_active = False


async def on_wake_word(conn: DeviceConnection, event: Event):
    """处理唤醒词事件

    唤醒流程:
    1. abort_xiaoai() 重启 mico_aivs_lab 服务中断云端处理
    2. start_recording(pcm="noop") 启动共享录音（音频通过 WebSocket 发来）
    3. 设置状态 WOKEN，等待二进制音频流

    注意: "noop" 是共享捕获设备 (dsnoop)，云端同样可以接收音频，
    因此必须配合 abort_xiaoai 阻止云端处理。
    start_recording 使用 fire-and-forget 发送（不等待响应），
    避免在 WebSocket 消息循环内死锁。
    """
    logger.info(f"唤醒: {conn.device_id}, wake_word={event.data}")

    # 停止自动播放队列 + 取消待执行的自动播放任务（消除竞态窗口）
    conn._queue_active = False
    if conn._auto_play_task and not conn._auto_play_task.done():
        conn._auto_play_task.cancel()
        conn._auto_play_task = None

    # 1. 中断小米云端
    await manager.send_request(conn.device_id, Request.abort_xiaoai())

    # 2. 启动共享录音 (pcm="noop" dsnoop 设备)
    #    fire-and-forget: 不 await 响应，避免死锁。
    #    记录 request id 以便在 handle_response 中检测失败。
    settings = get_settings()
    start_rec_req = Request.start_recording(
        pcm="noop",
        sample_rate=settings.audio.sample_rate,
        channels=settings.audio.channels,
        bits_per_sample=settings.audio.sample_width * 8,
    )
    conn._start_recording_id = start_rec_req.id
    await manager.send_request(conn.device_id, start_rec_req)

    # 3. 乐观设置状态 + 初始化音频缓冲
    #    假定 start_recording 成功；如果失败由 handle_response 回退。
    conn.state = ListeningState.WOKEN

    # 取消任何待处理的 instruction 定时器（避免云端 ASR 路径和本地录音并行处理）
    if conn._instruction_timer and not conn._instruction_timer.done():
        conn._instruction_timer.cancel()
        conn._instruction_timer = None
    conn._instruction_text = None
    conn._instruction_dispatched = False

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
            logger.info(f"唤醒超时，停止录音: {conn.device_id}")
            await manager.send_request(conn.device_id, Request.stop_recording())
            conn.state = ListeningState.IDLE

    conn._timeout_task = asyncio.create_task(wake_timeout())


async def on_audio_complete(conn: DeviceConnection):
    """处理录音完成（在独立 task 中运行，不阻塞 WebSocket 消息循环）"""
    logger.info(f"录音完成: {conn.device_id}")

    # 停止本地录音
    await manager.send_request(conn.device_id, Request.stop_recording())

    audio_data = conn.audio_buffer.stop()
    # 注意: conn.state 已在 handle_binary_message 中设为 PROCESSING

    # 取消待执行的自动播放任务（防止与用户命令竞态导致队列双重推进）
    if conn._auto_play_task and not conn._auto_play_task.done():
        conn._auto_play_task.cancel()
        conn._auto_play_task = None

    # 标记 pipeline 活跃 — 期间拦截云端播放命令
    conn._pipeline_active = True
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
        conn._pipeline_active = False
        conn.state = ListeningState.IDLE
