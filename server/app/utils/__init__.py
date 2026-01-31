"""
VoiceGrow 工具模块

通用工具函数和类
"""

import hashlib
import time
from typing import Optional

from .audio import pcm_to_wav, get_audio_duration, get_wav_duration, convert_sample_rate
from .logger import setup_logging, get_logger, StructuredFormatter


def generate_id(prefix: str = "") -> str:
    """
    生成唯一 ID

    Args:
        prefix: ID 前缀

    Returns:
        唯一 ID 字符串
    """
    import uuid
    unique_id = str(uuid.uuid4()).replace("-", "")[:16]
    if prefix:
        return f"{prefix}_{unique_id}"
    return unique_id


def hash_text(text: str, length: int = 16) -> str:
    """
    计算文本哈希

    Args:
        text: 输入文本
        length: 哈希长度

    Returns:
        哈希字符串
    """
    return hashlib.md5(text.encode()).hexdigest()[:length]


def format_duration(seconds: int) -> str:
    """
    格式化时长

    Args:
        seconds: 秒数

    Returns:
        格式化字符串 (如 "3:45")
    """
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


class RateLimiter:
    """
    简单的速率限制器
    """

    def __init__(self, max_calls: int, period: float):
        """
        Args:
            max_calls: 时间窗口内最大调用次数
            period: 时间窗口 (秒)
        """
        self.max_calls = max_calls
        self.period = period
        self.calls = []

    def is_allowed(self) -> bool:
        """检查是否允许调用"""
        now = time.time()

        # 清理过期记录
        self.calls = [t for t in self.calls if now - t < self.period]

        if len(self.calls) < self.max_calls:
            self.calls.append(now)
            return True

        return False

    def reset(self):
        """重置限制器"""
        self.calls = []
