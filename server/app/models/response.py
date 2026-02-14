"""
统一响应格式 + 错误码 + 业务异常

提供标准化的 API 响应结构
"""

from enum import IntEnum
from typing import Any, Optional


class ErrorCode(IntEnum):
    """错误码枚举"""
    SUCCESS = 0

    # 客户端错误 1001-1009
    INVALID_PARAMS = 1001
    MISSING_REQUIRED_FIELD = 1002
    INVALID_FORMAT = 1003
    UNAUTHORIZED = 1004
    FORBIDDEN = 1005
    RESOURCE_NOT_FOUND = 1006
    DUPLICATE_RESOURCE = 1007
    REQUEST_TOO_FREQUENT = 1008
    REQUEST_BODY_TOO_LARGE = 1009

    # 服务端错误 2001-2005
    INTERNAL_ERROR = 2001
    DATABASE_ERROR = 2002
    CACHE_ERROR = 2003
    STORAGE_ERROR = 2004
    SERVICE_UNAVAILABLE = 2005

    # 外部服务错误 3001-3008
    ASR_SERVICE_ERROR = 3001
    TTS_SERVICE_ERROR = 3002
    LLM_SERVICE_ERROR = 3003
    ASR_RECOGNITION_FAILED = 3004
    TTS_SYNTHESIS_FAILED = 3005
    LLM_GENERATION_FAILED = 3006
    AI_MANAGER_UNAVAILABLE = 3007
    AI_MANAGER_TIMEOUT = 3008

    # 业务错误 4001-4007
    CONTENT_NOT_FOUND = 4001
    CONTENT_UNAVAILABLE = 4002
    DEVICE_NOT_FOUND = 4003
    DEVICE_OFFLINE = 4004
    PLAYBACK_FAILED = 4005
    WORD_NOT_FOUND = 4006
    CATEGORY_NOT_FOUND = 4007
    YOUTUBE_DOWNLOAD_FAILED = 4008


class BusinessException(Exception):
    """自定义业务异常"""

    def __init__(self, code: ErrorCode, message: str, detail: Any = None):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


def success_response(data: Any = None, message: str = "success") -> dict:
    """构建成功响应"""
    resp = {
        "code": ErrorCode.SUCCESS,
        "message": message,
    }
    if data is not None:
        resp["data"] = data
    return resp


def error_response(code: ErrorCode, message: str, detail: Any = None) -> dict:
    """构建错误响应"""
    resp = {
        "code": int(code),
        "message": message,
    }
    if detail is not None:
        resp["detail"] = detail
    return resp
