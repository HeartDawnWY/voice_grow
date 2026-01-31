"""
播放队列服务

管理设备播放队列和播放模式
"""

import json
import random
import logging
from enum import Enum
from typing import Optional, List

from .redis_service import RedisService

logger = logging.getLogger(__name__)


class PlayMode(str, Enum):
    """播放模式"""
    SEQUENTIAL = "sequential"          # 顺序播放
    SINGLE_LOOP = "single_loop"        # 单曲循环
    PLAYLIST_LOOP = "playlist_loop"    # 列表循环
    SHUFFLE = "shuffle"                # 随机播放


class PlayQueueService:
    """
    播放队列服务

    Redis key:
    - voicegrow:queue:{device_id}:items  - 队列内容 ID 列表 (List)
    - voicegrow:queue:{device_id}:mode   - 播放模式 (String)
    - voicegrow:queue:{device_id}:index  - 当前播放索引 (String)
    """

    KEY_PREFIX = "voicegrow:queue"

    def __init__(self, redis_service: RedisService):
        self.redis = redis_service

    def _items_key(self, device_id: str) -> str:
        return f"{self.KEY_PREFIX}:{device_id}:items"

    def _mode_key(self, device_id: str) -> str:
        return f"{self.KEY_PREFIX}:{device_id}:mode"

    def _index_key(self, device_id: str) -> str:
        return f"{self.KEY_PREFIX}:{device_id}:index"

    async def set_mode(self, device_id: str, mode: PlayMode) -> None:
        """设置播放模式"""
        await self.redis.set(self._mode_key(device_id), mode.value)
        logger.info(f"设备 {device_id} 播放模式: {mode.value}")

    async def get_mode(self, device_id: str) -> PlayMode:
        """获取播放模式"""
        value = await self.redis.get(self._mode_key(device_id))
        if value:
            try:
                return PlayMode(value)
            except ValueError:
                pass
        return PlayMode.SEQUENTIAL

    async def add_to_queue(self, device_id: str, content_ids: List[int]) -> None:
        """添加内容到播放队列"""
        key = self._items_key(device_id)
        for cid in content_ids:
            await self.redis.client.rpush(key, str(cid))
        logger.info(f"设备 {device_id} 队列添加 {len(content_ids)} 个内容")

    async def get_next(self, device_id: str) -> Optional[int]:
        """获取下一个播放内容 ID"""
        mode = await self.get_mode(device_id)
        queue = await self.get_queue(device_id)

        if not queue:
            return None

        index_str = await self.redis.get(self._index_key(device_id))
        current_index = int(index_str) if index_str else -1

        if mode == PlayMode.SINGLE_LOOP:
            # 单曲循环: 返回当前歌曲
            next_index = current_index if 0 <= current_index < len(queue) else 0

        elif mode == PlayMode.SHUFFLE:
            # 随机播放
            next_index = random.randint(0, len(queue) - 1)

        elif mode == PlayMode.PLAYLIST_LOOP:
            # 列表循环
            next_index = (current_index + 1) % len(queue)

        else:
            # 顺序播放
            next_index = current_index + 1
            if next_index >= len(queue):
                return None  # 播放完毕

        await self.redis.set(self._index_key(device_id), str(next_index))
        return queue[next_index]

    async def get_previous(self, device_id: str) -> Optional[int]:
        """获取上一个播放内容 ID"""
        queue = await self.get_queue(device_id)

        if not queue:
            return None

        index_str = await self.redis.get(self._index_key(device_id))
        current_index = int(index_str) if index_str else 0

        prev_index = max(0, current_index - 1)
        await self.redis.set(self._index_key(device_id), str(prev_index))
        return queue[prev_index]

    async def clear_queue(self, device_id: str) -> None:
        """清空播放队列"""
        await self.redis.delete(
            self._items_key(device_id),
            self._index_key(device_id)
        )
        logger.info(f"设备 {device_id} 队列已清空")

    async def get_queue(self, device_id: str) -> List[int]:
        """获取播放队列"""
        key = self._items_key(device_id)
        result = await self.redis.client.lrange(key, 0, -1)
        return [int(x) for x in result] if result else []
