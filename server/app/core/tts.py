"""
TTS 语音合成服务

支持多后端：
- ai-manager: 外部 TTS API (基于 Google Cloud TTS)
- edge-tts: 本地 edge-tts 合成 + 文件缓存

核心契约: text in → URL out
"""

import asyncio
import logging
from abc import ABC, abstractmethod
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


class BaseTTSService(ABC):
    """
    TTS 服务抽象基类

    核心契约: text in → URL out
    子类只需实现 synthesize() 和 close()，
    其余便捷方法由基类统一提供。
    """

    def __init__(self, config: TTSConfig):
        self.config = config

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        language: str = "zh",
        speaking_rate: Optional[float] = None,
        pitch: Optional[float] = None,
        use_ssml: bool = False
    ) -> TTSResult:
        """合成语音，返回完整结果"""
        ...

    @abstractmethod
    async def close(self):
        """释放资源"""
        ...

    async def synthesize_to_url(
        self,
        text: str,
        language: str = "zh",
        speaking_rate: Optional[float] = None,
        pitch: Optional[float] = None,
        use_ssml: bool = False
    ) -> str:
        """合成语音并返回可直接播放的 URL"""
        result = await self.synthesize(text, language, speaking_rate, pitch, use_ssml)
        return result.audio_url

    async def synthesize_ssml(
        self,
        ssml: str,
        language: str = "zh"
    ) -> str:
        """使用 SSML 格式合成语音，返回 URL"""
        return await self.synthesize_to_url(ssml, language, use_ssml=True)

    async def synthesize_for_child(
        self,
        text: str,
        language: str = "zh"
    ) -> str:
        """儿童友好的语音合成 (语速略慢 0.85, 音调略高 1.0)"""
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
        """构建 SSML 文本"""
        voice = voice or self.config.voice_zh

        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
    <voice name="{voice}">
        <prosody rate="{rate}" pitch="{pitch}">
            {text}
        </prosody>
    </voice>
</speak>"""

        return ssml


class AIManagerTTSService(BaseTTSService):
    """
    ai-manager TTS 实现 (基于 Google Cloud TTS)

    特点:
    - 永久缓存: 相同文本只调用一次 API
    - 多账户轮换: 自动管理配额
    - 公开 URL: 返回 MinIO URL，可直接播放
    """

    # 可重试的 HTTP 状态码 (服务端暂时错误)
    _RETRYABLE_STATUS = {500, 502, 503, 504}

    def __init__(self, config: TTSConfig, minio_service=None):
        super().__init__(config)
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
            "speaking_rate": speaking_rate if speaking_rate is not None else self.config.speaking_rate,
            "pitch": pitch if pitch is not None else self.config.pitch,
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

    async def close(self):
        """关闭 HTTP 客户端"""
        async with self._lock:
            if self._client:
                await self._client.aclose()
                self._client = None


def create_tts_service(config: TTSConfig, minio_service=None) -> BaseTTSService:
    """
    TTS 服务工厂函数

    根据 config.backend 创建对应的 TTS 服务实例:
    - "ai-manager": AIManagerTTSService (默认)
    - "edge-tts": EdgeTTSService (本地合成)
    """
    if config.backend == "edge-tts":
        from .tts_edge import EdgeTTSService
        return EdgeTTSService(config, minio_service)
    return AIManagerTTSService(config, minio_service)


# 向后兼容别名 — 所有 import TTSService 的地方无需修改
TTSService = BaseTTSService
