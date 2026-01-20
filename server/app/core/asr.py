"""
ASR 语音识别服务

使用 faster-whisper 进行本地语音识别
"""

import asyncio
import struct
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

from ..config import ASRConfig

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


class ASRService:
    """
    语音识别服务

    使用 faster-whisper 进行本地语音识别
    """

    def __init__(self, config: ASRConfig):
        self.config = config
        self._model = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """初始化 Whisper 模型"""
        if self._model is not None:
            return

        async with self._lock:
            if self._model is not None:
                return

            logger.info(f"正在加载 Whisper 模型: {self.config.model_size}")

            # 在线程池中加载模型 (避免阻塞事件循环)
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None, self._load_model
            )

            logger.info("Whisper 模型加载完成")

    def _load_model(self):
        """加载模型 (同步)"""
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.config.model_size,
            device=self.config.device,
            compute_type=self.config.compute_type
        )

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """
        转录音频数据

        Args:
            audio_data: PCM 音频数据 (16-bit, mono)
            sample_rate: 采样率

        Returns:
            识别的文本
        """
        if self._model is None:
            await self.initialize()

        # 转换为 numpy 数组
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        # 如果采样率不是 16000，需要重采样
        if sample_rate != 16000:
            audio_array = await self._resample(audio_array, sample_rate, 16000)

        # 在线程池中执行识别 (避免阻塞事件循环)
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            self._transcribe_sync,
            audio_array
        )

        return text

    def _transcribe_sync(self, audio_array: np.ndarray) -> str:
        """同步转录"""
        segments, info = self._model.transcribe(
            audio_array,
            language=self.config.language,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad_filter,
            vad_parameters=self.config.vad_parameters
        )

        # 合并所有片段
        text = "".join([segment.text for segment in segments])
        return text.strip()

    async def transcribe_file(self, file_path: str) -> str:
        """
        从文件转录

        Args:
            file_path: 音频文件路径

        Returns:
            识别的文本
        """
        if self._model is None:
            await self.initialize()

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            self._transcribe_file_sync,
            file_path
        )

        return text

    def _transcribe_file_sync(self, file_path: str) -> str:
        """同步转录文件"""
        segments, info = self._model.transcribe(
            file_path,
            language=self.config.language,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad_filter
        )

        return "".join([segment.text for segment in segments]).strip()

    async def _resample(
        self,
        audio: np.ndarray,
        orig_sr: int,
        target_sr: int
    ) -> np.ndarray:
        """
        重采样音频

        Args:
            audio: 音频数据
            orig_sr: 原始采样率
            target_sr: 目标采样率

        Returns:
            重采样后的音频
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._resample_sync,
            audio,
            orig_sr,
            target_sr
        )

    def _resample_sync(
        self,
        audio: np.ndarray,
        orig_sr: int,
        target_sr: int
    ) -> np.ndarray:
        """同步重采样"""
        try:
            import librosa
            return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)
        except ImportError:
            # 简单的线性重采样 (质量较低)
            ratio = target_sr / orig_sr
            new_length = int(len(audio) * ratio)
            indices = np.linspace(0, len(audio) - 1, new_length)
            return np.interp(indices, np.arange(len(audio)), audio)
