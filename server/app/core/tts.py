"""
TTS 语音合成服务

使用外部 ai-manager TTS API (基于 Google Cloud TTS)
支持永久缓存、多账户轮换、公开 URL
"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass

import httpx

from ..config import TTSConfig
from ..utils.auth import generate_hmac_signature

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

    # 可重试的 HTTP 状态码 (服务端暂时错误)
    _RETRYABLE_STATUS = {500, 502, 503, 504}

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

        失败时抛出异常 (由调用方处理)

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

        # 构建请求数据
        data = {
            "text": text,
            "language_code": language_code,
            "voice_name": voice_name,
            "speaking_rate": speaking_rate or self.config.speaking_rate,
            "pitch": pitch or self.config.pitch,
            "audio_format": self.config.audio_format
        }

        if use_ssml:
            data["input_type"] = "ssml"

        last_error: Optional[Exception] = None

        # 重试: 首次 + 1 次重试
        for attempt in range(2):
            if attempt > 0:
                await asyncio.sleep(1.0)
                logger.info(f"TTS 重试第 {attempt} 次...")

            try:
                return await self._do_synthesize(data, voice_name, language_code)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    break  # 配额耗尽，不重试
                if e.response.status_code not in self._RETRYABLE_STATUS:
                    break
                logger.warning(
                    f"TTS API 可重试错误: {e.response.status_code} "
                    f"(attempt {attempt + 1}/2)"
                )
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                logger.warning(f"TTS 网络错误: {e} (attempt {attempt + 1}/2)")
            except Exception as e:
                last_error = e
                break

        # 所有重试均失败
        if isinstance(last_error, httpx.HTTPStatusError):
            if last_error.response.status_code == 429:
                logger.error("TTS quota exceeded - all accounts exhausted")
                raise Exception("语音服务暂时不可用，请稍后重试") from last_error
            logger.error(
                f"TTS API error: {last_error.response.status_code} - "
                f"{last_error.response.text}"
            )
            raise Exception(
                f"语音合成失败: {last_error.response.status_code}"
            ) from last_error
        else:
            logger.error(f"TTS synthesis failed: {last_error}")
            raise Exception("语音合成服务不可用") from last_error

    async def _do_synthesize(
        self, data: dict, voice_name: str, language_code: str
    ) -> TTSResult:
        """执行单次合成请求"""
        path = "/api/v1/tts/synthesize"
        timestamp, signature = self._sign("POST", path)

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        }

        client = await self._get_client()
        response = await client.post(path, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()

        logger.info(
            f"TTS synthesized: {len(data.get('text', ''))} chars, "
            f"cached={result.get('is_cached', False)}, "
            f"duration={result.get('duration_ms', 0)}ms"
        )

        return TTSResult(
            audio_url=result["audio_url"],
            duration_ms=result.get("duration_ms", 0),
            character_count=result.get("character_count", len(data.get("text", ""))),
            is_cached=result.get("is_cached", False),
            voice_name=result.get("voice_name", voice_name),
            language_code=result.get("language_code", language_code),
        )

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
        async with self._lock:
            if self._client:
                await self._client.aclose()
                self._client = None
