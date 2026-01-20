"""
VoiceGrow API 层

包含:
- WebSocket: open-xiaoai 客户端通信
- HTTP: REST API 接口
"""

from .websocket import router as websocket_router, ConnectionManager
from .http import router as http_router

__all__ = [
    "websocket_router",
    "http_router",
    "ConnectionManager",
]
