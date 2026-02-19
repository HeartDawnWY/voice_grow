"""
WebSocket API - open-xiaoai 客户端通信

处理与小爱音箱的 WebSocket 连接
端口: 4399
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

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
class PendingAction:
    """待确认操作（多轮对话状态）"""
    action_type: str              # 操作类型，如 "delete_content"
    data: Dict[str, Any]          # 操作数据
    handler_name: str             # 处理器名称，用于路由确认
    created_at: float = field(default_factory=time.time)
    timeout: float = 30.0         # 超时秒数

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.timeout


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

    # handler 中间播放计数器（play_tts/play_url 回调设置，防止拦截自己的播放）
    _handler_playback_count: int = 0

    # 播放队列活跃标记（播放完当前曲目后自动播下一首）
    _queue_active: bool = False

    # 自动播放下一首的待执行任务（防止重复触发）
    _auto_play_task: Optional[asyncio.Task] = None

    # 连续对话：pipeline 设置此标记，playing_state IDLE 事件驱动下一轮
    _continue_listening_pending: bool = False

    # 连续对话会话状态
    _in_conversation_session: bool = False           # 是否在连续对话中
    _waiting_speech_timeout_task: Optional[asyncio.Task] = None  # WAITING_SPEECH 超时

    # 待确认操作（多轮对话）
    pending_action: Optional[PendingAction] = None

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
                if conn._waiting_speech_timeout_task and not conn._waiting_speech_timeout_task.done():
                    conn._waiting_speech_timeout_task.cancel()

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
            logger.info(f"发送请求: {request.command}({payload_summary}) -> {device_id}")

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
            # 但放行 handler 自己发起的中间播放（TTS 提示/BGM 等）
            if state == PlayingState.PLAYING and conn._pipeline_active:
                if conn._handler_playback_count > 0:
                    conn._handler_playback_count -= 1
                    logger.debug(f"放行 handler 中间播放 (remaining={conn._handler_playback_count}, device={conn.device_id})")
                else:
                    logger.info(f"拦截云端抢先播放 (pipeline 活跃中, device={conn.device_id})")
                    await manager.send_request(conn.device_id, Request.abort_xiaoai())
                    await manager.send_request(conn.device_id, Request.pause())

            # 连续对话：提示音播完 → 进入 WAITING_SPEECH
            if state == PlayingState.IDLE and conn.state == ListeningState.PROMPTING:
                logger.info(f"提示音播完，进入 WAITING_SPEECH (device={conn.device_id})")
                await _enter_waiting_speech(conn)
                return

            # 连续对话：TTS 播完 + continue_listening_pending → 启动连续对话
            if (
                state == PlayingState.IDLE
                and conn._continue_listening_pending
                and conn.state == ListeningState.RESPONDING
            ):
                conn._continue_listening_pending = False
                logger.info(f"TTS 播完，启动连续对话 (device={conn.device_id})")
                asyncio.create_task(_continue_listening_session(conn))
                return

            # 自动播放下一首：播放结束 + 队列活跃 + pipeline 空闲
            if state == PlayingState.IDLE and conn._queue_active and not conn._pipeline_active:
                # 取消已有的待执行任务，防止重复触发
                if conn._auto_play_task and not conn._auto_play_task.done():
                    conn._auto_play_task.cancel()
                pipeline = get_pipeline()
                if pipeline and pipeline.play_queue_service:
                    conn._auto_play_task = asyncio.create_task(_auto_play_next(conn, pipeline))

    elif event.is_instruction():
        # 如果音频路径已激活（本地录音中/连续对话中），忽略 instruction 事件
        if conn.state in (
            ListeningState.WOKEN, ListeningState.LISTENING, ListeningState.PROCESSING,
            ListeningState.PROMPTING, ListeningState.WAITING_SPEECH,
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

        # 任何 instruction 活动（含 NewFile / 空 RecognizeResult）都应取消自动播放
        # 防止唤醒词后用户稍有停顿（>1.5s）时 auto_play 抢先推进队列
        if conn._auto_play_task and not conn._auto_play_task.done():
            conn._auto_play_task.cancel()
            conn._auto_play_task = None

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

    连续对话模式下，PROMPTING 时丢弃音频，WAITING_SPEECH 时检测持续语音。
    """
    if conn.state not in (
        ListeningState.WOKEN, ListeningState.LISTENING,
        ListeningState.PROMPTING, ListeningState.WAITING_SPEECH,
    ):
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

    # PROMPTING 状态：提示音播放中，丢弃音频（录音仍在运行但不处理）
    if conn.state == ListeningState.PROMPTING:
        if not hasattr(conn, '_prompting_frame_count'):
            conn._prompting_frame_count = 0
        conn._prompting_frame_count += 1
        if conn._prompting_frame_count % 50 == 1:
            logger.info(f"[DIAG] PROMPTING 帧 #{conn._prompting_frame_count}: pcm_size={len(pcm_data)} (device={conn.device_id})")
        return

    # WAITING_SPEECH 状态：检测持续语音，达标后进入 LISTENING
    if conn.state == ListeningState.WAITING_SPEECH:
        # 诊断日志：追踪帧到达情况
        if not hasattr(conn, '_ws_diag_count'):
            conn._ws_diag_count = 0
        conn._ws_diag_count += 1
        if conn._ws_diag_count % 50 == 1:  # 每 ~1s 记录一次
            import struct as _struct
            try:
                _samples = _struct.unpack(f"<{len(pcm_data) // 2}h", pcm_data)
                _rms = (sum(s ** 2 for s in _samples) / len(_samples)) ** 0.5 if _samples else 0
            except _struct.error:
                _rms = -1
            logger.info(
                f"[DIAG] WAITING_SPEECH 帧 #{conn._ws_diag_count}: "
                f"pcm_size={len(pcm_data)}, rms={_rms:.0f}, threshold={conn.audio_buffer.energy_threshold}, "
                f"voice_active={conn.audio_buffer._consecutive_voice_active} "
                f"(device={conn.device_id})"
            )

        settings = get_settings()
        if conn.audio_buffer.has_sustained_speech(pcm_data, settings.audio.min_speech_duration_ms):
            logger.info(f"检测到持续语音 (帧 #{conn._ws_diag_count})，进入 LISTENING (device={conn.device_id})")
            conn._ws_diag_count = 0
            # 取消等待超时
            if conn._waiting_speech_timeout_task and not conn._waiting_speech_timeout_task.done():
                conn._waiting_speech_timeout_task.cancel()
                conn._waiting_speech_timeout_task = None
            conn.state = ListeningState.LISTENING
            # 重新初始化主录音 buffer（从用户开口处开始收集）
            conn.audio_buffer = AudioBuffer(
                sample_rate=settings.audio.sample_rate,
                sample_width=settings.audio.sample_width,
                channels=settings.audio.channels,
                silence_threshold=settings.audio.silence_threshold,
                max_duration=settings.audio.max_duration,
                min_duration=settings.audio.min_duration,
            )
            conn.audio_buffer.start()
            conn.audio_buffer.append(pcm_data)
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
        conn.state = ListeningState.RESPONDING
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
        conn._handler_playback_count = 0

        # 安全检查：如果 pipeline 处理期间唤醒词到达，状态已被改为 WOKEN/LISTENING，
        # 不应覆盖，直接放弃连续对话逻辑
        if conn.state in (ListeningState.WOKEN, ListeningState.LISTENING):
            logger.info(f"跳过连续对话逻辑: 唤醒词已介入 (state={conn.state.value}, device={conn.device_id})")
            conn._continue_listening_pending = False
        elif conn._continue_listening_pending:
            # instruction 路径首次进入连续对话：需要 start_recording
            if not conn._in_conversation_session:
                try:
                    logger.info(f"连续对话 (instruction 路径): 启动录音 + 提示音 (device={conn.device_id})")
                    # 先设置状态和标记（在 await 之前！防止 IDLE 事件竞态）
                    conn.state = ListeningState.RESPONDING
                    conn._in_conversation_session = True
                    # _continue_listening_pending 保持 True（不清除）
                    # instruction 路径没有活跃录音，需要启动
                    settings = get_settings()
                    start_rec_req = Request.start_recording(
                        pcm="noop",
                        sample_rate=settings.audio.sample_rate,
                        channels=settings.audio.channels,
                        bits_per_sample=settings.audio.sample_width * 8,
                    )
                    conn._start_recording_id = start_rec_req.id
                    await manager.send_request(conn.device_id, start_rec_req)
                except Exception as e:
                    logger.error(f"连续对话启动录音失败: {e}", exc_info=True)
                    conn.state = ListeningState.IDLE
                    conn._in_conversation_session = False
                    conn._continue_listening_pending = False
            else:
                # 已在会话中：设置 RESPONDING，等 playing_state IDLE 事件驱动
                conn.state = ListeningState.RESPONDING
                logger.info(f"等待 TTS 播完触发连续对话 (instruction 路径, device={conn.device_id})")
        elif conn._in_conversation_session:
            # 在会话中但 continue_listening=False（告别词）→ 退出对话
            logger.info(f"告别词检测到 (instruction 路径)，退出连续对话 (device={conn.device_id})")
            await _exit_conversation(conn)
        else:
            # 非连续对话 instruction 路径：重置为 IDLE
            conn.state = ListeningState.IDLE


async def _start_listening_session_initial(conn: DeviceConnection):
    """启动录音监听会话 — 唤醒词专用

    流程:
    1. abort_xiaoai() 中断云端处理
    2. start_recording(pcm="noop") 启动共享录音
    3. 设置状态 WOKEN，初始化 AudioBuffer
    4. 启动唤醒超时定时器
    """
    # 1. 中断小米云端
    await manager.send_request(conn.device_id, Request.abort_xiaoai())

    # 2. 启动共享录音 (pcm="noop" dsnoop 设备)
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
    conn.state = ListeningState.WOKEN

    # 取消任何待处理的 instruction 定时器
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

    # 4. 唤醒超时
    async def wake_timeout():
        await asyncio.sleep(settings.audio.wake_timeout)
        if conn.state == ListeningState.WOKEN:
            logger.info(f"唤醒超时，停止录音: {conn.device_id}")
            await manager.send_request(conn.device_id, Request.stop_recording())
            conn.state = ListeningState.IDLE

    conn._timeout_task = asyncio.create_task(wake_timeout())
    logger.info(f"监听会话已启动 (device={conn.device_id})")


async def _continue_listening_session(conn: DeviceConnection):
    """启动连续对话监听 — TTS 播完后调用

    与 _start_listening_session_initial 的区别:
    - 不调 abort_xiaoai（连续对话期间无需重复中断）
    - 不调 start/stop_recording（录音不停）
    - 设 state = PROMPTING，播放 "叮~" 提示音
    - 由 playing_state IDLE 事件驱动进入 WAITING_SPEECH
    """
    conn._in_conversation_session = True
    conn.state = ListeningState.PROMPTING

    # 播放 "叮~" 提示音
    settings = get_settings()
    prompt_url = _get_prompt_sound_url(settings.audio.prompt_sound_path)
    if prompt_url:
        await manager.send_request(conn.device_id, Request.play_url(prompt_url))
        logger.info(f"连续对话: 播放提示音 (device={conn.device_id})")
    else:
        # 提示音 URL 不可用，直接进入 WAITING_SPEECH
        logger.warning(f"提示音 URL 不可用，直接进入 WAITING_SPEECH (device={conn.device_id})")
        await _enter_waiting_speech(conn)
        return

    # 安全超时：3 秒后如果 playing_state IDLE 事件没来（提示音播放失败），强制进入
    async def _prompting_safety_timeout():
        await asyncio.sleep(3.0)
        if conn.state == ListeningState.PROMPTING:
            logger.warning(f"提示音安全超时，强制进入 WAITING_SPEECH (device={conn.device_id})")
            await _enter_waiting_speech(conn)

    conn._timeout_task = asyncio.create_task(_prompting_safety_timeout())


async def _enter_waiting_speech(conn: DeviceConnection):
    """进入 WAITING_SPEECH 状态（等待用户开口）

    初始化语音检测用 AudioBuffer 和 15s 超时任务。
    """
    # 取消安全超时
    if conn._timeout_task and not conn._timeout_task.done():
        conn._timeout_task.cancel()
        conn._timeout_task = None

    conn.state = ListeningState.WAITING_SPEECH
    conn._ws_diag_count = 0  # 重置诊断计数器
    conn._prompting_frame_count = 0

    # 初始化用于语音检测的 AudioBuffer（reset 持续语音检测状态）
    settings = get_settings()
    conn.audio_buffer = AudioBuffer(
        sample_rate=settings.audio.sample_rate,
        sample_width=settings.audio.sample_width,
        channels=settings.audio.channels,
        silence_threshold=settings.audio.silence_threshold,
        max_duration=settings.audio.max_duration,
        min_duration=settings.audio.min_duration,
    )
    conn.audio_buffer.reset_sustained_speech()

    # 15s 超时：无语音 → 退出对话
    async def _speech_timeout():
        await asyncio.sleep(settings.audio.continue_speech_timeout)
        if conn.state == ListeningState.WAITING_SPEECH:
            diag_count = getattr(conn, '_ws_diag_count', 0)
            logger.info(
                f"WAITING_SPEECH 超时 ({settings.audio.continue_speech_timeout}s)，"
                f"共收到 {diag_count} 帧音频，退出对话 (device={conn.device_id})"
            )
            await _exit_conversation(conn)

    # 取消已有的等待超时
    if conn._waiting_speech_timeout_task and not conn._waiting_speech_timeout_task.done():
        conn._waiting_speech_timeout_task.cancel()
    conn._waiting_speech_timeout_task = asyncio.create_task(_speech_timeout())

    logger.info(f"进入 WAITING_SPEECH (device={conn.device_id})")


async def _exit_conversation(conn: DeviceConnection):
    """退出连续对话（播放 "嘟~" → stop_recording → IDLE）"""
    if not conn._in_conversation_session:
        return  # 已退出或从未进入，幂等保护
    logger.info(f"退出连续对话 (device={conn.device_id})")

    # 清理超时任务
    if conn._waiting_speech_timeout_task and not conn._waiting_speech_timeout_task.done():
        conn._waiting_speech_timeout_task.cancel()
        conn._waiting_speech_timeout_task = None
    if conn._timeout_task and not conn._timeout_task.done():
        conn._timeout_task.cancel()
        conn._timeout_task = None

    # 播放退出音 "嘟~"
    settings = get_settings()
    exit_url = _get_prompt_sound_url(settings.audio.exit_sound_path)
    if exit_url:
        await manager.send_request(conn.device_id, Request.play_url(exit_url))

    # 停止录音
    await manager.send_request(conn.device_id, Request.stop_recording())

    # 重置状态
    conn.state = ListeningState.IDLE
    conn._in_conversation_session = False
    conn._continue_listening_pending = False
    conn._queue_active = False  # 防止退出音 IDLE 事件触发 auto_play
    conn._instruction_dispatched = False  # 清理，确保下次 instruction 事件正常触发


def _get_prompt_sound_url(minio_path: str) -> Optional[str]:
    """根据 MinIO 对象路径生成公网 URL"""
    settings = get_settings()
    if not settings.minio.public_base_url:
        return None
    base = settings.minio.public_base_url.rstrip("/")
    return f"{base}/{minio_path}"


async def on_wake_word(conn: DeviceConnection, event: Event):
    """处理唤醒词事件"""
    logger.info(f"唤醒: {conn.device_id}, wake_word={event.data}")

    # 停止自动播放队列 + 取消待执行的自动播放任务（消除竞态窗口）
    conn._queue_active = False
    if conn._auto_play_task and not conn._auto_play_task.done():
        conn._auto_play_task.cancel()
        conn._auto_play_task = None

    # 取消现有超时任务（防止 PROMPTING 安全超时等孤儿任务）
    if conn._timeout_task and not conn._timeout_task.done():
        conn._timeout_task.cancel()
        conn._timeout_task = None

    # 如果在连续对话中，先清理会话状态 + stop_recording
    if conn._in_conversation_session:
        logger.info(f"唤醒中断连续对话 (device={conn.device_id})")
        if conn._waiting_speech_timeout_task and not conn._waiting_speech_timeout_task.done():
            conn._waiting_speech_timeout_task.cancel()
            conn._waiting_speech_timeout_task = None
        conn._in_conversation_session = False
        conn._continue_listening_pending = False
        await manager.send_request(conn.device_id, Request.stop_recording())

    await _start_listening_session_initial(conn)


async def on_audio_complete(conn: DeviceConnection):
    """处理录音完成（在独立 task 中运行，不阻塞 WebSocket 消息循环）"""
    logger.info(f"录音完成: {conn.device_id}")

    in_session = conn._in_conversation_session

    if not in_session:
        # 首次唤醒路径：停止录音 + 中断小爱
        await manager.send_request(conn.device_id, Request.stop_recording())
    # 连续对话路径：不停止录音，不调 abort_xiaoai

    audio_data = conn.audio_buffer.stop()
    # 注意: conn.state 已在 handle_binary_message 中设为 PROCESSING

    # 取消待执行的自动播放任务（防止与用户命令竞态导致队列双重推进）
    if conn._auto_play_task and not conn._auto_play_task.done():
        conn._auto_play_task.cancel()
        conn._auto_play_task = None

    if not in_session:
        # 中断小爱原生响应（提前发送，ASR+NLU+Handler 期间完成 restart）
        try:
            await manager.send_request(conn.device_id, Request.abort_xiaoai())
        except Exception as e:
            logger.warning(f"中断小爱失败: {e}")

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
        conn._handler_playback_count = 0

        # 安全检查：如果 pipeline 处理期间唤醒词到达，状态已被改为 WOKEN/LISTENING，
        # 不应覆盖，直接放弃连续对话逻辑
        if conn.state in (ListeningState.WOKEN, ListeningState.LISTENING):
            logger.info(f"跳过连续对话逻辑: 唤醒词已介入 (state={conn.state.value}, device={conn.device_id})")
            conn._continue_listening_pending = False
        elif conn._continue_listening_pending:
            # continue_listening=True：保持 RESPONDING 状态，等 playing_state IDLE 事件驱动
            # 不在此处启动 _continue_listening_session，由事件驱动
            logger.info(f"等待 TTS 播完触发连续对话 (device={conn.device_id})")
        elif conn._in_conversation_session:
            # 使用 live 值（非快照）：唤醒词可能在 pipeline 处理期间改变了会话状态
            # 在会话中但 continue_listening=False（如告别词）→ 退出对话
            logger.info(f"告别词检测到，退出连续对话 (device={conn.device_id})")
            await _exit_conversation(conn)
        else:
            conn.state = ListeningState.IDLE
