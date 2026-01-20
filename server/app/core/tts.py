"""
TTS 语音合成服务

使用外部 ai-manager TTS API (基于 Google Cloud TTS)
支持永久缓存、多账户轮换、公开 URL
"""

import asyncio
import hmac
import hashlib
import time
import logging
from typing import Optional
from dataclasses import dataclass

import httpx

from ..config import TTSConfig

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """TTS 合成结果"""
    audio_url: str
    duration_ms: int
    character_count: int
    is_cached: bool
    voice_name: str
    language_code: str


class TTSService:
    """
    TTS 语音合成服务

    调用外部 ai-manager TTS API (基于 Google Cloud TTS)
    特点:
    - 永久缓存: 相同文本只调用一次 API
    - 多账户轮换: 自动管理配额
    - 公开 URL: 返回 MinIO URL，可直接播放
    """

    def __init__(self, config: TTSConfig, minio_service=None):
        """
        初始化 TTS 服务

        Args:
            config: TTS 配置
            minio_service: MinIO 服务实例 (可选，ai-manager 已包含存储)
        """
        self.config = config
        self.minio_service = minio_service
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端 (懒加载)"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout
            )
        return self._client

    def _generate_signature(self, method: str, path: str) -> tuple[str, str]:
        """
        生成 HMAC-SHA256 签名

        签名算法: HMAC-SHA256(SECRET_KEY, API_KEY + TIMESTAMP + HTTP_METHOD + PATH)

        Returns:
            (timestamp, signature) 元组
        """
        timestamp = str(int(time.time()))
        message = f"{self.config.api_key}{timestamp}{method.upper()}{path}"
        signature = hmac.new(
            self.config.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    async def synthesize(
        self,
        text: str,
        language: str = "zh",
        speaking_rate: Optional[float] = None,
        pitch: Optional[float] = None,
        use_ssml: bool = False
    ) -> TTSResult:
        """
        合成语音，返回完整结果

        Args:
            text: 要合成的文本 (或 SSML 内容)
            language: 语言 ("zh" 或 "en")
            speaking_rate: 语速 (0.25-4.0，默认使用配置值)
            pitch: 音调 (-20.0 到 20.0)
            use_ssml: 是否使用 SSML 格式

        Returns:
            TTSResult 包含 audio_url, duration_ms, is_cached 等信息
        """
        # 确定语言代码和音色
        if language == "zh":
            language_code = "zh-CN"
            voice_name = self.config.voice_zh
        else:
            language_code = "en-US"
            voice_name = self.config.voice_en

        # 构建请求
        path = "/api/v1/tts/synthesize"
        timestamp, signature = self._generate_signature("POST", path)

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature
        }

        data = {
            "text": text,
            "language_code": language_code,
            "voice_name": voice_name,
            "speaking_rate": speaking_rate or self.config.speaking_rate,
            "pitch": pitch or self.config.pitch,
            "audio_format": self.config.audio_format
        }

        # SSML 模式
        if use_ssml:
            data["input_type"] = "ssml"

        # 发送请求
        client = await self._get_client()

        try:
            response = await client.post(path, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()

            logger.info(
                f"TTS synthesized: {len(text)} chars, "
                f"cached={result.get('is_cached', False)}, "
                f"duration={result.get('duration_ms', 0)}ms"
            )

            return TTSResult(
                audio_url=result["audio_url"],
                duration_ms=result.get("duration_ms", 0),
                character_count=result.get("character_count", len(text)),
                is_cached=result.get("is_cached", False),
                voice_name=result.get("voice_name", voice_name),
                language_code=result.get("language_code", language_code)
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.error("TTS quota exceeded - all accounts exhausted")
                raise Exception("语音服务暂时不可用，请稍后重试")
            else:
                logger.error(f"TTS API error: {e.response.status_code} - {e.response.text}")
                raise Exception(f"语音合成失败: {e.response.status_code}")

        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            raise

    async def synthesize_to_url(
        self,
        text: str,
        language: str = "zh",
        speaking_rate: Optional[float] = None,
        pitch: Optional[float] = None,
        use_ssml: bool = False
    ) -> str:
        """
        合成语音并返回可直接播放的 URL

        Args:
            text: 要合成的文本 (或 SSML 内容)
            language: 语言 ("zh" 或 "en")
            speaking_rate: 语速 (0.25-4.0，默认使用配置值)
            pitch: 音调 (-20.0 到 20.0)
            use_ssml: 是否使用 SSML 格式

        Returns:
            音频文件的公开 URL (MinIO)
        """
        result = await self.synthesize(text, language, speaking_rate, pitch, use_ssml)
        return result.audio_url

    async def synthesize_ssml(
        self,
        ssml: str,
        language: str = "zh"
    ) -> str:
        """
        使用 SSML 格式合成语音

        SSML 支持:
        - <speak> 根标签（必需）
        - <break time="500ms"/> 停顿
        - <emphasis level="strong">重点</emphasis> 强调
        - <prosody rate="slow">慢速</prosody> 语速控制

        示例:
            <speak>
                你好！<break time="300ms"/>
                <emphasis level="strong">欢迎</emphasis>来到声伴成长。
            </speak>

        Returns:
            音频文件的公开 URL
        """
        return await self.synthesize_to_url(ssml, language, use_ssml=True)

    async def synthesize_for_child(
        self,
        text: str,
        language: str = "zh"
    ) -> str:
        """
        儿童友好的语音合成

        - 语速略慢 (0.85)
        - 音调略高 (1.0)
        - 适合儿童收听

        Args:
            text: 要合成的文本
            language: 语言

        Returns:
            音频文件的公开 URL
        """
        return await self.synthesize_to_url(
            text,
            language,
            speaking_rate=0.85,
            pitch=1.0
        )

    def build_ssml(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: str = "1.0",
        pitch: str = "0%",
        breaks: Optional[list] = None
    ) -> str:
        """
        构建 SSML 文本

        Args:
            text: 要合成的文本
            voice: 音色名称 (可选)
            rate: 语速 (0.5-2.0)
            pitch: 音调 (-50% 到 +50%)
            breaks: 停顿列表 [(位置, 时长ms), ...]

        Returns:
            SSML 字符串
        """
        voice = voice or self.config.voice_zh

        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
    <voice name="{voice}">
        <prosody rate="{rate}" pitch="{pitch}">
            {text}
        </prosody>
    </voice>
</speak>"""

        return ssml

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None
