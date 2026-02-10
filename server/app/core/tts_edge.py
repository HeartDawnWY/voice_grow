"""
edge-tts 本地语音合成服务

使用 edge-tts 库进行本地合成，文件缓存到磁盘，
通过 FastAPI StaticFiles 提供静态 URL 访问。
"""

import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

import edge_tts

from ..config import TTSConfig
from .tts import BaseTTSService, TTSResult

logger = logging.getLogger(__name__)


class EdgeTTSService(BaseTTSService):
    """
    edge-tts 本地合成实现

    特点:
    - 本地合成: 无需外部 API，使用 Microsoft Edge TTS
    - 文件缓存: hash(text+voice+rate+pitch) 作为缓存键，相同请求直接返回
    - 原子写入: 先写临时文件，再 os.replace() 防止并发损坏
    - 静态 URL: 通过 FastAPI StaticFiles 提供 HTTP 访问
    """

    def __init__(self, config: TTSConfig):
        super().__init__(config)
        self.cache_dir = Path(config.edge_cache_dir)
        self.base_url = config.edge_base_url.rstrip("/")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

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
        edge-tts 使用百分比偏移 (e.g. "+10%", "-5%")。
        粗略换算: 1 半音 ≈ 6% 频率变化，此处简化为 5%/半音。
        """
        p = pitch if pitch is not None else self.config.pitch
        pct = round(p * 5)
        if pct >= 0:
            return f"+{pct}%"
        return f"{pct}%"

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

        合成结果缓存到本地文件，返回静态 URL。
        注意: edge-tts 不支持 SSML 输入，use_ssml=True 时会
        将内容作为纯文本处理并记录警告。
        """
        if use_ssml:
            logger.warning(
                "edge-tts 后端不支持 SSML 输入，将作为纯文本处理。"
                "如需 SSML 支持，请切换到 ai-manager 后端。"
            )

        # 选择音色
        if language == "zh":
            voice = self.config.edge_voice_zh
            language_code = "zh-CN"
        else:
            voice = self.config.edge_voice_en
            language_code = "en-US"

        rate_str = self._rate_string(speaking_rate)
        pitch_str = self._pitch_string(pitch)

        # 缓存检查
        key = self._cache_key(text, voice, rate_str, pitch_str)
        filename = f"{key}.mp3"
        filepath = self.cache_dir / filename

        if filepath.exists():
            file_size = filepath.stat().st_size
            logger.info(
                f"TTS cache hit: {key}, size={file_size}B, "
                f"text={text[:30]}..."
            )
            return TTSResult(
                audio_url=f"{self.base_url}/{filename}",
                duration_ms=0,
                character_count=len(text),
                is_cached=True,
                voice_name=voice,
                language_code=language_code,
            )

        # 合成 — 写入临时文件，原子替换到最终路径
        tmp_path = self.cache_dir / f"{key}.{uuid.uuid4().hex[:8]}.tmp"
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate_str,
                pitch=pitch_str,
            )
            await communicate.save(str(tmp_path))
            os.replace(str(tmp_path), str(filepath))
        except Exception as e:
            # 清理残留临时文件
            tmp_path.unlink(missing_ok=True)
            logger.error(f"edge-tts 合成失败: {e}")
            raise Exception("语音合成失败，请稍后重试") from e

        file_size = filepath.stat().st_size
        logger.info(
            f"TTS synthesized (edge-tts): {len(text)} chars, "
            f"voice={voice}, size={file_size}B"
        )

        return TTSResult(
            audio_url=f"{self.base_url}/{filename}",
            duration_ms=0,
            character_count=len(text),
            is_cached=False,
            voice_name=voice,
            language_code=language_code,
        )

    async def close(self):
        """无需清理资源"""
        pass
