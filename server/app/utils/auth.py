"""
ai-manager HMAC-SHA256 认证工具

所有 ai-manager API 服务 (ASR/TTS/LLM) 共用的签名生成逻辑
"""

import hmac
import hashlib
import time


def generate_hmac_signature(
    api_key: str,
    secret_key: str,
    method: str,
    path: str,
) -> tuple[str, str]:
    """
    生成 HMAC-SHA256 签名

    签名算法: HMAC-SHA256(SECRET_KEY, API_KEY + TIMESTAMP + HTTP_METHOD + PATH)

    Args:
        api_key: API 密钥
        secret_key: 签名密钥
        method: HTTP 方法 (GET, POST, ...)
        path: 请求路径 (如 /api/v1/stt/transcribe)

    Returns:
        (timestamp, signature) 元组
    """
    timestamp = str(int(time.time()))
    message = f"{api_key}{timestamp}{method.upper()}{path}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return timestamp, signature
