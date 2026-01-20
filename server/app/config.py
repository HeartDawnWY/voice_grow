"""
VoiceGrow 配置管理模块

统一管理所有服务配置，支持环境变量和配置文件
"""

from dataclasses import dataclass, field
from typing import Optional
import os
from functools import lru_cache


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    websocket_port: int = 4399      # open-xiaoai WebSocket 端口
    http_port: int = 8000           # HTTP API 端口
    debug: bool = False


@dataclass
class ASRConfig:
    """ASR 语音识别配置 (faster-whisper)"""
    model_size: str = "small"       # tiny, base, small, medium, large-v3
    device: str = "cpu"             # cpu, cuda
    compute_type: str = "int8"      # float16, int8, int8_float16
    language: str = "zh"            # 主要语言
    beam_size: int = 5
    vad_filter: bool = True
    vad_parameters: dict = field(default_factory=lambda: {
        "min_silence_duration_ms": 500,
        "speech_pad_ms": 200
    })


@dataclass
class TTSConfig:
    """TTS 语音合成配置 (ai-manager API)"""
    # ai-manager 服务配置
    base_url: str = "http://ai-manager:8000"
    api_key: str = ""
    secret_key: str = ""

    # 音色配置 (Google Cloud TTS voices)
    voice_zh: str = "zh-CN-Neural2-C"           # 中文女声
    voice_en: str = "en-US-Neural2-C"           # 英文女声

    # 语音参数
    speaking_rate: float = 0.9                   # 语速 (0.25-4.0)
    pitch: float = 0.0                           # 音调 (-20.0 到 20.0)
    audio_format: str = "MP3"                    # 音频格式

    # 超时配置
    timeout: int = 30


@dataclass
class LLMConfig:
    """LLM 对话配置 (ai-manager API)"""
    # ai-manager 服务配置
    base_url: str = "http://ai-manager:8000"
    api_key: str = ""
    secret_key: str = ""

    # 模型配置
    model_preference: str = "gemini-2.0-flash-exp"  # 首选模型

    # 生成参数
    max_tokens: int = 300
    temperature: float = 0.7
    timeout: int = 30

    # 儿童对话系统提示
    system_prompt: str = """你是小声，一个专为儿童设计的智能语音助手。

请遵循以下规则：
1. 使用简单、易懂的语言，适合 3-10 岁儿童
2. 回答要简短，适合语音播放（不超过 100 字）
3. 保持友好、温暖的语气，像一个有耐心的大姐姐
4. 不讨论任何不适合儿童的话题
5. 对于不确定的问题，诚实说"我不太确定，我们可以一起查一查"
6. 鼓励好奇心和学习，多用"你真棒"、"好问题"等鼓励语"""


@dataclass
class DatabaseConfig:
    """MySQL 数据库配置"""
    host: str = "localhost"
    port: int = 3306
    user: str = "voicegrow"
    password: str = ""
    database: str = "voicegrow"
    pool_size: int = 5
    pool_recycle: int = 3600

    @property
    def url(self) -> str:
        """SQLAlchemy 连接 URL"""
        return f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass
class MinIOConfig:
    """MinIO 对象存储配置"""
    endpoint: str = "localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = "voicegrow"
    secure: bool = False

    # 预签名 URL 有效期 (秒)
    presign_expiry: int = 3600


@dataclass
class RedisConfig:
    """Redis 缓存配置"""
    host: str = "localhost"
    port: int = 6379
    password: Optional[str] = None
    db: int = 0

    # 会话过期时间 (秒)
    session_ttl: int = 1800


@dataclass
class AudioConfig:
    """音频处理配置"""
    sample_rate: int = 16000        # 采样率 (Hz)
    sample_width: int = 2           # 采样宽度 (bytes), 16-bit = 2
    channels: int = 1               # 声道数

    # VAD 参数
    silence_threshold: float = 0.5  # 静音阈值 (秒)
    max_duration: float = 10.0      # 最大录音时长 (秒)
    min_duration: float = 0.3       # 最小录音时长 (秒)

    # 唤醒后超时
    wake_timeout: float = 5.0       # 唤醒后等待说话的超时 (秒)


@dataclass
class Settings:
    """全局配置"""
    server: ServerConfig = field(default_factory=ServerConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    minio: MinIOConfig = field(default_factory=MinIOConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量加载配置"""
        return cls(
            server=ServerConfig(
                host=os.getenv("SERVER_HOST", "0.0.0.0"),
                websocket_port=int(os.getenv("WEBSOCKET_PORT", "4399")),
                http_port=int(os.getenv("HTTP_PORT", "8000")),
                debug=os.getenv("DEBUG", "false").lower() == "true",
            ),
            asr=ASRConfig(
                model_size=os.getenv("ASR_MODEL_SIZE", "small"),
                device=os.getenv("ASR_DEVICE", "cpu"),
                compute_type=os.getenv("ASR_COMPUTE_TYPE", "int8"),
                language=os.getenv("ASR_LANGUAGE", "zh"),
            ),
            tts=TTSConfig(
                base_url=os.getenv("TTS_BASE_URL", "http://ai-manager:8000"),
                api_key=os.getenv("TTS_API_KEY", ""),
                secret_key=os.getenv("TTS_SECRET_KEY", ""),
                voice_zh=os.getenv("TTS_VOICE_ZH", "zh-CN-Neural2-C"),
                voice_en=os.getenv("TTS_VOICE_EN", "en-US-Neural2-C"),
                speaking_rate=float(os.getenv("TTS_SPEAKING_RATE", "0.9")),
                pitch=float(os.getenv("TTS_PITCH", "0.0")),
                timeout=int(os.getenv("TTS_TIMEOUT", "30")),
            ),
            llm=LLMConfig(
                base_url=os.getenv("LLM_BASE_URL", "http://ai-manager:8000"),
                api_key=os.getenv("LLM_API_KEY", ""),
                secret_key=os.getenv("LLM_SECRET_KEY", ""),
                model_preference=os.getenv("LLM_MODEL", "gemini-2.0-flash-exp"),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "300")),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
                timeout=int(os.getenv("LLM_TIMEOUT", "30")),
            ),
            database=DatabaseConfig(
                host=os.getenv("MYSQL_HOST", "localhost"),
                port=int(os.getenv("MYSQL_PORT", "3306")),
                user=os.getenv("MYSQL_USER", "voicegrow"),
                password=os.getenv("MYSQL_PASSWORD", ""),
                database=os.getenv("MYSQL_DATABASE", "voicegrow"),
            ),
            minio=MinIOConfig(
                endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
                access_key=os.getenv("MINIO_ACCESS_KEY", ""),
                secret_key=os.getenv("MINIO_SECRET_KEY", ""),
                bucket=os.getenv("MINIO_BUCKET", "voicegrow"),
                secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
            ),
            redis=RedisConfig(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD"),
                db=int(os.getenv("REDIS_DB", "0")),
            ),
            audio=AudioConfig(
                sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", "16000")),
                silence_threshold=float(os.getenv("AUDIO_SILENCE_THRESHOLD", "0.5")),
                max_duration=float(os.getenv("AUDIO_MAX_DURATION", "10.0")),
                wake_timeout=float(os.getenv("AUDIO_WAKE_TIMEOUT", "5.0")),
            ),
        )


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例"""
    return Settings.from_env()
