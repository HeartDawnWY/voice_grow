"""
设备管理 + 统计 API 路由
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query, Depends, Request

from ...models.schemas import DeviceCommandRequest
from ...models.response import ErrorCode, BusinessException, success_response
from ..deps import get_content_service
from ...services.content_service import ContentService

router = APIRouter()
logger = logging.getLogger(__name__)


# ========== 设备管理 API ==========

@router.get("/api/v1/devices")
async def list_devices():
    """获取已连接的设备列表"""
    from ..websocket import manager

    devices = []
    for device_id, conn in manager.connections.items():
        devices.append({
            "device_id": device_id,
            "state": conn.state.value,
            "playing_state": conn.playing_state.value,
        })

    return success_response(data={"devices": devices, "total": len(devices)})


@router.get("/api/v1/devices/{device_id}")
async def get_device_detail(device_id: str):
    """获取设备详情"""
    from ..websocket import manager

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    data = {
        "device_id": device_id,
        "state": conn.state.value,
        "playing_state": conn.playing_state.value,
        "current_content": conn.current_content,
    }
    return success_response(data=data)


@router.post("/api/v1/devices/{device_id}/command")
async def device_command(
    device_id: str,
    body: DeviceCommandRequest,
    http_request: Request,
):
    """通用命令发送"""
    from ..websocket import manager
    from ...models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    command = body.command
    params = body.params

    if command == "play_url":
        url = params.get("url", "")
        if not url:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Missing 'url' param")
        await manager.send_request(device_id, ProtocolRequest.play_url(url))
    elif command == "pause":
        await manager.send_request(device_id, ProtocolRequest.pause())
    elif command == "play":
        await manager.send_request(device_id, ProtocolRequest.play())
    elif command == "volume_up":
        await manager.send_request(device_id, ProtocolRequest.volume_up())
    elif command == "volume_down":
        await manager.send_request(device_id, ProtocolRequest.volume_down())
    elif command == "speak":
        text = params.get("text", "")
        if not text:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Missing 'text' param")
        tts_service = http_request.app.state.tts_service
        audio_url = await tts_service.synthesize_to_url(text)
        await manager.send_request(device_id, ProtocolRequest.play_url(audio_url))
        return success_response(data={"audio_url": audio_url})
    elif command == "wake_up":
        silent = params.get("silent", False)
        await manager.send_request(device_id, ProtocolRequest.wake_up(silent=silent))
    elif command == "run_shell":
        script = params.get("script", "")
        if not script:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Missing 'script' param")
        await manager.send_request(device_id, ProtocolRequest.run_shell(script))
    elif command == "stop_recording":
        await manager.send_request(device_id, ProtocolRequest.stop_recording())
    else:
        raise BusinessException(ErrorCode.INVALID_PARAMS, f"Unknown command: {command}")

    return success_response()


@router.post("/api/devices/{device_id}/play")
async def device_play_url(
    device_id: str,
    url: str = Query(..., description="音频 URL")
):
    """让设备播放指定 URL"""
    from ..websocket import manager
    from ...models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    await manager.send_request(device_id, ProtocolRequest.play_url(url))
    return success_response()


@router.post("/api/devices/{device_id}/speak")
async def device_speak(
    device_id: str,
    http_request: Request,
    speak_text: str = Query(..., description="要播放的文本"),
):
    """让设备播放语音 (TTS)"""
    from ..websocket import manager
    from ...models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    tts_service = http_request.app.state.tts_service
    audio_url = await tts_service.synthesize_to_url(speak_text)

    await manager.send_request(device_id, ProtocolRequest.play_url(audio_url))
    return success_response(data={"audio_url": audio_url})


@router.post("/api/devices/{device_id}/pause")
async def device_pause(device_id: str):
    """暂停设备播放"""
    from ..websocket import manager
    from ...models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    await manager.send_request(device_id, ProtocolRequest.pause())
    return success_response()


@router.post("/api/devices/{device_id}/resume")
async def device_resume(device_id: str):
    """继续设备播放"""
    from ..websocket import manager
    from ...models.protocol import Request as ProtocolRequest

    conn = manager.get_connection(device_id)
    if not conn:
        raise BusinessException(ErrorCode.DEVICE_NOT_FOUND, "Device not connected")

    await manager.send_request(device_id, ProtocolRequest.play())
    return success_response()


# ========== 统计 API ==========

@router.get("/api/v1/stats")
async def get_stats(
    http_request: Request,
    content_service: ContentService = Depends(get_content_service)
):
    """获取系统统计信息"""
    from ..websocket import manager

    stats = await content_service.get_stats()

    return success_response(data={
        "connected_devices": len(manager.connections),
        "version": "0.1.0",
        **stats
    })


@router.get("/api/v1/stats/playback")
async def get_playback_stats(
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    content_service: ContentService = Depends(get_content_service)
):
    """播放统计 (日期范围)"""
    stats = await content_service.get_stats()
    return success_response(data={
        "total_plays": stats.get("total_play_count", 0),
        "total_duration": 0,
        "top_contents": [],
        "daily_stats": [],
    })
