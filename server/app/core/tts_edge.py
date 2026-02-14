"""
edge-tts 语音合成服务

使用 edge-tts 库进行本地合成，音频上传到 MinIO，
通过 VPS Nginx 反代 + 缓存提供公网访问。
"""

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path
from typing import Optional

import edge_tts
from edge_tts.exceptions import EdgeTTSException

from ..config import TTSConfig
from .tts import BaseTTSService, TTSResult

logger = logging.getLogger(__name__)


class EdgeTTSService(BaseTTSService):
    """
    edge-tts + MinIO 实现

    流程: edge-tts 合成 → 上传 MinIO → 返回公网 URL (VPS Nginx 反代)
    缓存: hash(text+voice+rate+pitch) 去重，MinIO 中已存在则直接返回 URL
    """

    MINIO_PREFIX = "tts"

    def __init__(self, config: TTSConfig, minio_service):
        super().__init__(config)
        if minio_service is None:
            raise ValueError("edge-tts 后端需要 MinIO 服务，请检查 MinIO 配置")
        self.minio_service = minio_service
        # 临时目录: 合成后上传 MinIO，随即删除
        self.tmp_dir = Path(config.edge_cache_dir)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(
        self,
        text: str,
        voice: str,
        rate: str,
        pitch: str,
    ) -> str:
        """生成缓存键 (基于内容 hash)"""
        raw = f"{text}|{voice}|{rate}|{pitch}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _rate_string(self, speaking_rate: Optional[float]) -> str:
        """将数值语速转换为 edge-tts 格式 (e.g. "-10%", "+20%")"""
        rate = speaking_rate if speaking_rate is not None else self.config.speaking_rate
        pct = round((rate - 1.0) * 100)
        if pct >= 0:
            return f"+{pct}%"
        return f"{pct}%"

    def _pitch_string(self, pitch: Optional[float]) -> str:
        """
        将数值音调转换为 edge-tts 格式

        ai-manager 使用半音刻度 (-20.0 ~ 20.0)，
        edge-tts 要求 Hz 偏移格式 (e.g. "+10Hz", "-5Hz")。
        粗略换算: 1 半音 ≈ 6% 频率变化，基频约 200Hz，
        1 半音 ≈ 12Hz，此处简化为 10Hz/半音。
        """
        p = pitch if pitch is not None else self.config.pitch
        hz = round(p * 10)
        if hz >= 0:
            return f"+{hz}Hz"
        return f"{hz}Hz"

    def _object_name(self, key: str) -> str:
        """MinIO 对象路径"""
        return f"{self.MINIO_PREFIX}/{key}.mp3"

    async def synthesize(
        self,
        text: str,
        language: str = "zh",
        speaking_rate: Optional[float] = None,
        pitch: Optional[float] = None,
        use_ssml: bool = False
    ) -> TTSResult:
        """
        使用 edge-tts 合成语音

        合成结果上传到 MinIO，返回公网 URL。
        """
        if use_ssml:
            logger.warning(
                "edge-tts 后端不支持 SSML 输入，将作为纯文本处理。"
                "如需 SSML 支持，请切换到 ai-manager 后端。"
            )

        voice = self.config.edge_voice_zh if language == "zh" else self.config.edge_voice_en
        language_code = "zh-CN" if language == "zh" else "en-US"

        rate_str = self._rate_string(speaking_rate)
        pitch_str = self._pitch_string(pitch)

        key = self._cache_key(text, voice, rate_str, pitch_str)
        object_name = self._object_name(key)

        # 检查 MinIO 中是否已存在 (相同内容不重复合成)
        if await self.minio_service.exists(object_name):
            logger.info(
                f"TTS cache hit (MinIO): {key}, text={text[:30]}..."
            )
            return TTSResult(
                audio_url=self.minio_service.get_public_url(object_name),
                duration_ms=0,
                character_count=len(text),
                is_cached=True,
                voice_name=voice,
                language_code=language_code,
            )

        # 合成到临时文件 → 上传 MinIO → 删除临时文件 (带重试)
        max_retries = 3
        tmp_path = self.tmp_dir / f"{key}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    communicate = edge_tts.Communicate(
                        text=text,
                        voice=voice,
                        rate=rate_str,
                        pitch=pitch_str,
                    )
                    await communicate.save(str(tmp_path))
                    break
                except (ConnectionError, OSError, EdgeTTSException) as e:
                    if attempt == max_retries:
                        raise
                    logger.warning(
                        f"edge-tts 连接失败 (第{attempt}次), 重试中: {e}"
                    )
                    await asyncio.sleep(0.5 * attempt)

            file_size = tmp_path.stat().st_size

            await self.minio_service.upload_file(
                str(tmp_path), object_name, content_type="audio/mpeg"
            )

            logger.info(
                f"TTS synthesized (edge-tts → MinIO): {len(text)} chars, "
                f"voice={voice}, size={file_size}B, object={object_name}"
            )
        except Exception as e:
            logger.error(f"edge-tts 合成/上传失败: {e}")
            raise Exception("语音合成失败，请稍后重试") from e
        finally:
            tmp_path.unlink(missing_ok=True)

        return TTSResult(
            audio_url=self.minio_service.get_public_url(object_name),
            duration_ms=0,
            character_count=len(text),
            is_cached=False,
            voice_name=voice,
            language_code=language_code,
        )

    async def close(self):
        """无需清理资源"""
        pass
