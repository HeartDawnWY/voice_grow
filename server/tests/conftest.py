"""
测试公共 fixtures
"""

import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# 确保 server/ 目录在 Python 路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.websocket import DeviceConnection, set_pipeline


@pytest.fixture
def conn():
    """创建测试用 DeviceConnection（跳过 get_settings 依赖）"""
    return DeviceConnection(
        device_id="test-device",
        websocket=MagicMock(),
        audio_buffer=MagicMock(),  # 提供 mock 避免触发 __post_init__ 中的 get_settings
    )


@pytest.fixture
def mock_manager():
    """Mock 全局 ConnectionManager，拦截所有 send_request 调用"""
    with patch("app.api.websocket.manager") as m:
        m.send_request = AsyncMock(return_value=None)
        m.get_connection = MagicMock()
        yield m


@pytest.fixture
def mock_pipeline():
    """Mock VoicePipeline，通过 set_pipeline 注入全局"""
    pipeline = MagicMock()
    pipeline.process_text = AsyncMock()
    pipeline.respond = AsyncMock()
    pipeline.play_queue_service = MagicMock()
    pipeline.content_service = MagicMock()
    set_pipeline(pipeline)
    yield pipeline
    set_pipeline(None)
