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
        try:
            await self.redis.set(self._mode_key(device_id), mode.value)
            logger.info(f"设备 {device_id} 播放模式: {mode.value}")
        except Exception as e:
            logger.warning(f"设置播放模式失败(device={device_id}): {e}")

    async def get_mode(self, device_id: str) -> PlayMode:
        """获取播放模式"""
        try:
            value = await self.redis.get(self._mode_key(device_id))
            if value:
                try:
                    return PlayMode(value)
                except ValueError:
                    pass
        except Exception as e:
            logger.warning(f"获取播放模式失败(device={device_id}): {e}")
        return PlayMode.SEQUENTIAL

    async def set_queue(self, device_id: str, content_ids: List[int], start_index: int = 0) -> None:
        """设置播放队列（清空旧队列并初始化）"""
        try:
            await self.clear_queue(device_id)
            key = self._items_key(device_id)
            for cid in content_ids:
                await self.redis.client.rpush(key, str(cid))
            await self.redis.set(self._index_key(device_id), str(start_index))
            logger.info(f"设备 {device_id} 队列设置 {len(content_ids)} 个内容, 起始={start_index}")
        except Exception as e:
            logger.warning(f"设置播放队列失败(device={device_id}): {e}")

    async def add_to_queue(self, device_id: str, content_ids: List[int]) -> None:
        """添加内容到播放队列"""
        try:
            key = self._items_key(device_id)
            for cid in content_ids:
                await self.redis.client.rpush(key, str(cid))
            logger.info(f"设备 {device_id} 队列添加 {len(content_ids)} 个内容")
        except Exception as e:
            logger.warning(f"添加播放队列失败(device={device_id}): {e}")

    async def get_next(self, device_id: str, wrap: bool = False) -> Optional[int]:
        """获取下一个播放内容 ID

        Args:
            wrap: 是否循环。True=手动切歌（永远循环），False=自动续播（尊重播放模式）
        """
        try:
            mode = await self.get_mode(device_id)
            queue = await self.get_queue(device_id)

            if not queue:
                return None

            index_str = await self.redis.get(self._index_key(device_id))
            current_index = int(index_str) if index_str else -1

            if mode == PlayMode.SINGLE_LOOP:
                next_index = current_index if 0 <= current_index < len(queue) else 0

            elif mode == PlayMode.SHUFFLE:
                next_index = random.randint(0, len(queue) - 1)

            elif mode == PlayMode.PLAYLIST_LOOP or wrap:
                # 列表循环 or 手动切歌: 到末尾回绕到开头
                next_index = (current_index + 1) % len(queue)

            else:
                # 顺序播放 + 自动续播: 到末尾停止
                next_index = current_index + 1
                if next_index >= len(queue):
                    return None

            await self.redis.set(self._index_key(device_id), str(next_index))
            return queue[next_index]
        except Exception as e:
            logger.warning(f"获取下一首失败(device={device_id}): {e}")
            return None

    async def get_previous(self, device_id: str, wrap: bool = False) -> Optional[int]:
        """获取上一个播放内容 ID

        Args:
            wrap: 是否循环。True=手动切歌（永远循环），False=尊重播放模式
        """
        try:
            mode = await self.get_mode(device_id)
            queue = await self.get_queue(device_id)

            if not queue:
                return None

            index_str = await self.redis.get(self._index_key(device_id))
            current_index = int(index_str) if index_str else 0

            if mode == PlayMode.SINGLE_LOOP:
                prev_index = current_index if 0 <= current_index < len(queue) else 0

            elif mode == PlayMode.SHUFFLE:
                prev_index = random.randint(0, len(queue) - 1)

            elif mode == PlayMode.PLAYLIST_LOOP or wrap:
                # 列表循环 or 手动切歌: 在第一首时回绕到最后
                prev_index = (current_index - 1) % len(queue)

            else:
                # 顺序播放 + 非手动: 已是第一首则返回 None
                if current_index <= 0:
                    return None
                prev_index = current_index - 1

            await self.redis.set(self._index_key(device_id), str(prev_index))
            return queue[prev_index]
        except Exception as e:
            logger.warning(f"获取上一首失败(device={device_id}): {e}")
            return None

    async def clear_queue(self, device_id: str) -> None:
        """清空播放队列"""
        try:
            await self.redis.delete(
                self._items_key(device_id),
                self._index_key(device_id)
            )
            logger.info(f"设备 {device_id} 队列已清空")
        except Exception as e:
            logger.warning(f"清空播放队列失败(device={device_id}): {e}")

    async def get_queue(self, device_id: str) -> List[int]:
        """获取播放队列"""
        try:
            key = self._items_key(device_id)
            result = await self.redis.client.lrange(key, 0, -1)
            return [int(x) for x in result] if result else []
        except Exception as e:
            logger.warning(f"获取播放队列失败(device={device_id}): {e}")
            return []
