"""
ASR 语音识别服务

调用外部 ai-manager STT API (基于 faster-whisper large-v3)
"""

import asyncio
import io
import struct
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

from ..config import ASRConfig
from ..utils.audio import pcm_to_wav
from ..utils.auth import generate_hmac_signature

logger = logging.getLogger(__name__)


@dataclass
class AudioBuffer:
    """
    音频缓冲器

    收集音频流直到检测到语音结束 (基于静音检测)
    """

    sample_rate: int = 16000
    sample_width: int = 2           # 16-bit
    channels: int = 1

    # VAD 相关参数
    silence_threshold: float = 0.5  # 静音阈值 (秒)
    max_duration: float = 10.0      # 最大录音时长 (秒)
    min_duration: float = 0.3       # 最小录音时长 (秒)

    # 能量阈值 (RMS)
    energy_threshold: int = 500

    # 内部状态
    _buffer: bytearray = field(default_factory=bytearray)
    _is_recording: bool = False
    _last_voice_time: float = 0.0
    _start_time: float = 0.0

    def start(self):
        """开始录音"""
        self._buffer = bytearray()
        self._is_recording = True
        self._start_time = time.time()
        self._last_voice_time = time.time()
        logger.debug("AudioBuffer: 开始录音")

    def append(self, data: bytes):
        """
        追加音频数据

        Args:
            data: PCM 音频数据
        """
        if not self._is_recording:
            return

        self._buffer.extend(data)

        # 检测语音活动
        if self._has_voice_activity(data):
            self._last_voice_time = time.time()

    def should_stop(self) -> bool:
        """判断是否应该停止录音"""
        if not self._is_recording:
            return True

        elapsed = time.time() - self._start_time
        silence_duration = time.time() - self._last_voice_time

        # 超过最大时长
        if elapsed >= self.max_duration:
            logger.debug(f"AudioBuffer: 达到最大录音时长 {self.max_duration}s")
            return True

        # 静音超过阈值且已有足够录音
        if silence_duration >= self.silence_threshold and elapsed >= self.min_duration:
            logger.debug(f"AudioBuffer: 静音 {silence_duration:.2f}s，停止录音")
            return True

        return False

    def stop(self) -> bytes:
        """停止录音并返回音频数据"""
        self._is_recording = False
        audio_data = bytes(self._buffer)
        duration = len(audio_data) / (self.sample_rate * self.sample_width * self.channels)
        logger.info(f"AudioBuffer: 录音完成，时长 {duration:.2f}s，大小 {len(audio_data)} bytes")
        return audio_data

    def get_duration(self) -> float:
        """获取当前录音时长"""
        return len(self._buffer) / (self.sample_rate * self.sample_width * self.channels)

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def _has_voice_activity(self, data: bytes) -> bool:
        """
        简单的语音活动检测 (基于能量)

        Args:
            data: PCM 音频数据

        Returns:
            是否检测到语音
        """
        if len(data) < 2:
            return False

        try:
            # 计算 RMS 能量
            samples = struct.unpack(f"<{len(data) // 2}h", data)
            if len(samples) == 0:
                return False

            rms = (sum(s ** 2 for s in samples) / len(samples)) ** 0.5
            return rms > self.energy_threshold
        except struct.error:
            return False


@dataclass
class ASRResult:
    """ASR 识别结果"""
    text: str
    language: str
    duration_ms: int
    processing_time_ms: int
    segments: List[Dict]


class ASRService:
    """
    语音识别服务

    调用外部 ai-manager STT API (基于 faster-whisper large-v3)
    特点:
    - GPU 加速: 远程 CUDA 推理
    - 高精度: large-v3 模型
    - VAD 过滤: Silero VAD 静音过滤
    """

    # 可重试的 HTTP 状态码 (服务端暂时错误)
    _RETRYABLE_STATUS = {500, 502, 503, 504}

    def __init__(self, config: ASRConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端 (懒加载，线程安全)"""
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        base_url=self.config.base_url,
                        timeout=httpx.Timeout(
                            connect=5.0,
                            read=self.config.timeout,
                            write=10.0,
                            pool=5.0,
                        ),
                    )
        return self._client

    def _sign(self, method: str, path: str) -> tuple[str, str]:
        """生成请求签名"""
        return generate_hmac_signature(
            self.config.api_key, self.config.secret_key, method, path,
        )

    async def initialize(self):
        """初始化 ASR 服务 (验证远程服务连接)"""
        client = await self._get_client()
        try:
            response = await client.get("/api/v1/stt/health")
            if response.status_code == 200:
                health = response.json()
                logger.info(
                    f"ASR 服务连接成功: model={health.get('model_size')}, "
                    f"device={health.get('device')}, "
                    f"gpu={health.get('gpu_available')}"
                )
            else:
                logger.warning(f"ASR 服务健康检查失败: {response.status_code}")
        except Exception as e:
            logger.warning(f"ASR 服务连接失败 (将在首次调用时重试): {e}")

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """
        转录音频数据

        失败时返回空字符串 (由调用方处理空结果提示)

        Args:
            audio_data: PCM 音频数据 (16-bit, mono)
            sample_rate: 采样率

        Returns:
            识别的文本，失败时返回空字符串
        """
        try:
            result = await self.transcribe_with_details(audio_data, sample_rate)
            return result.text
        except Exception as e:
            logger.error(f"ASR transcribe failed: {e}")
            return ""

    async def transcribe_with_details(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
    ) -> ASRResult:
        """
        转录音频数据 (完整接口，返回详细结果)

        Args:
            audio_data: PCM 音频数据 (16-bit, mono)
            sample_rate: 采样率

        Returns:
            ASRResult 包含 text, segments, duration_ms 等信息

        Raises:
            Exception: API 调用失败时抛出
        """
        # PCM → WAV
        wav_data = pcm_to_wav(audio_data, sample_rate=sample_rate)

        last_error: Optional[Exception] = None

        # 重试: 首次 + 1 次重试
        for attempt in range(2):
            if attempt > 0:
                await asyncio.sleep(1.0)
                logger.info(f"ASR 重试第 {attempt} 次...")

            try:
                return await self._do_transcribe(wav_data)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code not in self._RETRYABLE_STATUS:
                    break
                logger.warning(
                    f"ASR API 可重试错误: {e.response.status_code} (attempt {attempt + 1}/2)"
                )
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                logger.warning(f"ASR 网络错误: {e} (attempt {attempt + 1}/2)")
            except Exception as e:
                last_error = e
                break

        # 所有重试均失败
        if isinstance(last_error, httpx.HTTPStatusError):
            logger.error(
                f"ASR API error: {last_error.response.status_code} - "
                f"{last_error.response.text}"
            )
            raise Exception(
                f"语音识别失败: {last_error.response.status_code}"
            ) from last_error
        else:
            logger.error(f"ASR transcription failed: {last_error}")
            raise Exception("语音识别服务不可用") from last_error

    async def _do_transcribe(self, wav_data: bytes) -> ASRResult:
        """执行单次转录请求"""
        path = "/api/v1/stt/transcribe"
        timestamp, signature = self._sign("POST", path)

        headers = {
            "X-API-Key": self.config.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        }

        params = {
            "language": self.config.language,
            "beam_size": self.config.beam_size,
            "vad_filter": str(self.config.vad_filter).lower(),
        }

        files = {
            "file": ("audio.wav", io.BytesIO(wav_data), "audio/wav"),
        }

        client = await self._get_client()

        response = await client.post(
            path, headers=headers, params=params, files=files,
        )
        response.raise_for_status()
        result = response.json()

        text = result.get("text", "").strip()
        logger.info(
            f"ASR 识别完成: '{text[:50]}', "
            f"duration={result.get('duration_ms', 0)}ms, "
            f"processing={result.get('processing_time_ms', 0)}ms"
        )

        return ASRResult(
            text=text,
            language=result.get("language", self.config.language),
            duration_ms=result.get("duration_ms", 0),
            processing_time_ms=result.get("processing_time_ms", 0),
            segments=result.get("segments", []),
        )

    async def close(self):
        """关闭 HTTP 客户端"""
        async with self._lock:
            if self._client:
                await self._client.aclose()
                self._client = None
