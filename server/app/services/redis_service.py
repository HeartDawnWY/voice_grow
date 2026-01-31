"""
Redis 缓存服务

提供缓存操作，支持：
- 内容缓存 (content)
- 分类缓存 (category)
- 艺术家缓存 (artist)
- 标签缓存 (tag)
- 设备会话缓存 (device session)
- ASR/TTS 结果缓存
- 搜索结果缓存
"""

import json
import hashlib
import logging
from typing import Optional, List, Dict, Any, Union
from datetime import timedelta

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from ..config import RedisConfig

logger = logging.getLogger(__name__)


class RedisService:
    """
    Redis 缓存服务

    Key 命名规范: {业务}:{对象类型}:{标识}:{字段}
    例如:
    - content:123                    # 单个内容详情
    - content:list:story:5           # 分类下内容列表
    - content:hot:music              # 热门音乐列表
    - category:tree:story            # 故事分类树
    - artist:1                       # 艺术家详情
    - artist:contents:1              # 艺术家作品列表
    - tag:list:age                   # 年龄标签列表
    - device:abc123:session          # 设备会话
    - device:abc123:history          # 设备播放历史
    - asr:{audio_hash}               # ASR 识别结果
    - tts:{text_hash}                # TTS 音频路径
    - search:{keyword_hash}:story    # 搜索结果
    """

    def __init__(self, config: RedisConfig):
        self.config = config
        self.pool: Optional[ConnectionPool] = None
        self._client: Optional[redis.Redis] = None

    async def initialize(self):
        """初始化 Redis 连接池"""
        try:
            self.pool = ConnectionPool.from_url(
                self.config.url,
                max_connections=self.config.max_connections,
                decode_responses=True,  # 自动解码为字符串
            )
            self._client = redis.Redis(connection_pool=self.pool)

            # 测试连接
            await self._client.ping()
            logger.info(f"Redis connected: {self.config.host}:{self.config.port}")
        except Exception as e:
            logger.error(f"Failed to connect Redis: {e}")
            raise

    async def close(self):
        """关闭 Redis 连接"""
        if self._client:
            await self._client.close()
        if self.pool:
            await self.pool.disconnect()
        logger.info("Redis connection closed")

    @property
    def client(self) -> redis.Redis:
        """获取 Redis 客户端"""
        if not self._client:
            raise RuntimeError("Redis not initialized")
        return self._client

    # =====================================================
    # 通用操作
    # =====================================================

    async def get(self, key: str) -> Optional[str]:
        """获取字符串值"""
        return await self.client.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None
    ) -> bool:
        """设置字符串值"""
        if ttl and ttl > 0:
            return await self.client.setex(key, ttl, value)
        return await self.client.set(key, value)

    async def delete(self, *keys: str) -> int:
        """删除键"""
        if not keys:
            return 0
        return await self.client.delete(*keys)

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        return await self.client.exists(key) > 0

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """获取 JSON 值"""
        data = await self.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None

    async def set_json(
        self,
        key: str,
        value: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """设置 JSON 值"""
        return await self.set(key, json.dumps(value, ensure_ascii=False), ttl)

    # =====================================================
    # 内容缓存
    # =====================================================

    def _content_key(self, content_id: int) -> str:
        return f"content:{content_id}"

    def _content_list_key(self, content_type: str, category_id: int) -> str:
        return f"content:list:{content_type}:{category_id}"

    def _content_hot_key(self, content_type: str) -> str:
        return f"content:hot:{content_type}"

    async def get_content(self, content_id: int) -> Optional[Dict[str, Any]]:
        """获取内容缓存"""
        return await self.get_json(self._content_key(content_id))

    async def set_content(self, content_id: int, data: Dict[str, Any]) -> bool:
        """设置内容缓存"""
        return await self.set_json(
            self._content_key(content_id),
            data,
            self.config.content_ttl
        )

    async def delete_content(self, content_id: int) -> int:
        """删除内容缓存"""
        return await self.delete(self._content_key(content_id))

    async def get_content_list(
        self,
        content_type: str,
        category_id: int
    ) -> Optional[List[Dict[str, Any]]]:
        """获取分类内容列表缓存"""
        data = await self.get_json(self._content_list_key(content_type, category_id))
        return data if isinstance(data, list) else None

    async def set_content_list(
        self,
        content_type: str,
        category_id: int,
        data: List[Dict[str, Any]]
    ) -> bool:
        """设置分类内容列表缓存"""
        return await self.set_json(
            self._content_list_key(content_type, category_id),
            data,
            self.config.content_list_ttl
        )

    async def get_hot_contents(self, content_type: str) -> Optional[List[int]]:
        """获取热门内容 ID 列表 (ZSet)"""
        key = self._content_hot_key(content_type)
        result = await self.client.zrevrange(key, 0, -1)
        return [int(x) for x in result] if result else None

    async def set_hot_contents(
        self,
        content_type: str,
        contents: List[tuple[int, float]]  # [(content_id, score), ...]
    ) -> bool:
        """设置热门内容 (ZSet)"""
        key = self._content_hot_key(content_type)
        if not contents:
            return False
        # 清除旧数据并设置新数据
        pipe = self.client.pipeline()
        pipe.delete(key)
        for content_id, score in contents:
            pipe.zadd(key, {str(content_id): score})
        pipe.expire(key, self.config.content_hot_ttl)
        await pipe.execute()
        return True

    async def increment_play_count(self, content_type: str, content_id: int) -> None:
        """增加热门内容播放计数"""
        key = self._content_hot_key(content_type)
        await self.client.zincrby(key, 1, str(content_id))

    # =====================================================
    # 分类缓存
    # =====================================================

    def _category_tree_key(self, content_type: str) -> str:
        return f"category:tree:{content_type}"

    def _category_key(self, category_id: int) -> str:
        return f"category:{category_id}"

    async def get_category_tree(self, content_type: str) -> Optional[List[Dict[str, Any]]]:
        """获取分类树缓存"""
        data = await self.get_json(self._category_tree_key(content_type))
        return data if isinstance(data, list) else None

    async def set_category_tree(
        self,
        content_type: str,
        data: List[Dict[str, Any]]
    ) -> bool:
        """设置分类树缓存"""
        return await self.set_json(
            self._category_tree_key(content_type),
            data,
            self.config.category_tree_ttl
        )

    async def get_category(self, category_id: int) -> Optional[Dict[str, Any]]:
        """获取单个分类缓存"""
        return await self.get_json(self._category_key(category_id))

    async def set_category(self, category_id: int, data: Dict[str, Any]) -> bool:
        """设置单个分类缓存"""
        return await self.set_json(
            self._category_key(category_id),
            data,
            self.config.category_tree_ttl
        )

    async def invalidate_category_cache(self, content_type: Optional[str] = None) -> None:
        """清除分类缓存"""
        keys = []
        if content_type:
            keys.append(self._category_tree_key(content_type))
        else:
            # 清除所有类型的分类树
            for ct in ["story", "music", "english", "sound"]:
                keys.append(self._category_tree_key(ct))
        if keys:
            await self.delete(*keys)

    # =====================================================
    # 艺术家缓存
    # =====================================================

    def _artist_key(self, artist_id: int) -> str:
        return f"artist:{artist_id}"

    def _artist_contents_key(self, artist_id: int) -> str:
        return f"artist:contents:{artist_id}"

    def _artist_search_key(self, keyword: str) -> str:
        return f"artist:search:{self._hash_key(keyword)}"

    async def get_artist(self, artist_id: int) -> Optional[Dict[str, Any]]:
        """获取艺术家缓存"""
        return await self.get_json(self._artist_key(artist_id))

    async def set_artist(self, artist_id: int, data: Dict[str, Any]) -> bool:
        """设置艺术家缓存"""
        return await self.set_json(
            self._artist_key(artist_id),
            data,
            self.config.artist_ttl
        )

    async def get_artist_contents(self, artist_id: int) -> Optional[List[int]]:
        """获取艺术家作品 ID 列表"""
        data = await self.get_json(self._artist_contents_key(artist_id))
        return data if isinstance(data, list) else None

    async def set_artist_contents(
        self,
        artist_id: int,
        content_ids: List[int]
    ) -> bool:
        """设置艺术家作品 ID 列表"""
        return await self.set_json(
            self._artist_contents_key(artist_id),
            content_ids,
            self.config.artist_ttl
        )

    async def delete_artist_cache(self, artist_id: int) -> None:
        """删除艺术家相关缓存"""
        await self.delete(
            self._artist_key(artist_id),
            self._artist_contents_key(artist_id)
        )

    # =====================================================
    # 标签缓存
    # =====================================================

    def _tag_list_key(self, tag_type: str) -> str:
        return f"tag:list:{tag_type}"

    def _tag_contents_key(self, tag_id: int) -> str:
        return f"tag:contents:{tag_id}"

    async def get_tag_list(self, tag_type: str) -> Optional[List[Dict[str, Any]]]:
        """获取标签列表缓存"""
        data = await self.get_json(self._tag_list_key(tag_type))
        return data if isinstance(data, list) else None

    async def set_tag_list(
        self,
        tag_type: str,
        data: List[Dict[str, Any]]
    ) -> bool:
        """设置标签列表缓存"""
        return await self.set_json(
            self._tag_list_key(tag_type),
            data,
            self.config.tag_list_ttl
        )

    async def get_tag_contents(self, tag_id: int) -> Optional[List[int]]:
        """获取标签关联内容 ID 列表"""
        data = await self.get_json(self._tag_contents_key(tag_id))
        return data if isinstance(data, list) else None

    async def set_tag_contents(self, tag_id: int, content_ids: List[int]) -> bool:
        """设置标签关联内容 ID 列表"""
        return await self.set_json(
            self._tag_contents_key(tag_id),
            content_ids,
            self.config.content_list_ttl
        )

    # =====================================================
    # 设备会话缓存
    # =====================================================

    def _device_session_key(self, device_id: str) -> str:
        return f"device:{device_id}:session"

    def _device_history_key(self, device_id: str) -> str:
        return f"device:{device_id}:history"

    async def get_device_session(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备会话"""
        return await self.get_json(self._device_session_key(device_id))

    async def set_device_session(
        self,
        device_id: str,
        data: Dict[str, Any]
    ) -> bool:
        """设置设备会话（不过期）"""
        return await self.set_json(
            self._device_session_key(device_id),
            data,
            self.config.session_ttl if self.config.session_ttl > 0 else None
        )

    async def update_device_session(
        self,
        device_id: str,
        **kwargs
    ) -> bool:
        """更新设备会话部分字段"""
        session = await self.get_device_session(device_id) or {}
        session.update(kwargs)
        return await self.set_device_session(device_id, session)

    async def delete_device_session(self, device_id: str) -> int:
        """删除设备会话"""
        return await self.delete(self._device_session_key(device_id))

    async def add_to_history(
        self,
        device_id: str,
        content_id: int,
        max_size: int = 100
    ) -> None:
        """添加到播放历史（保留最近 N 条）"""
        key = self._device_history_key(device_id)
        pipe = self.client.pipeline()
        pipe.lpush(key, str(content_id))
        pipe.ltrim(key, 0, max_size - 1)
        if self.config.history_ttl > 0:
            pipe.expire(key, self.config.history_ttl)
        await pipe.execute()

    async def get_device_history(
        self,
        device_id: str,
        limit: int = 20
    ) -> List[int]:
        """获取播放历史"""
        key = self._device_history_key(device_id)
        result = await self.client.lrange(key, 0, limit - 1)
        return [int(x) for x in result] if result else []

    # =====================================================
    # ASR/TTS 缓存
    # =====================================================

    @staticmethod
    def _hash_key(data: Union[str, bytes]) -> str:
        """生成哈希键"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return hashlib.md5(data).hexdigest()

    def _asr_key(self, audio_hash: str) -> str:
        return f"asr:{audio_hash}"

    def _tts_key(self, text_hash: str) -> str:
        return f"tts:{text_hash}"

    async def get_asr_result(self, audio_data: bytes) -> Optional[str]:
        """获取 ASR 缓存结果"""
        key = self._asr_key(self._hash_key(audio_data))
        return await self.get(key)

    async def set_asr_result(self, audio_data: bytes, text: str) -> bool:
        """设置 ASR 缓存结果"""
        key = self._asr_key(self._hash_key(audio_data))
        return await self.set(key, text, self.config.asr_ttl)

    async def get_tts_path(self, text: str, voice: str = "") -> Optional[str]:
        """获取 TTS 缓存路径"""
        cache_key = f"{text}:{voice}" if voice else text
        key = self._tts_key(self._hash_key(cache_key))
        return await self.get(key)

    async def set_tts_path(
        self,
        text: str,
        audio_path: str,
        voice: str = ""
    ) -> bool:
        """设置 TTS 缓存路径"""
        cache_key = f"{text}:{voice}" if voice else text
        key = self._tts_key(self._hash_key(cache_key))
        return await self.set(key, audio_path, self.config.tts_ttl)

    # =====================================================
    # 搜索缓存
    # =====================================================

    def _search_key(self, keyword: str, content_type: Optional[str] = None) -> str:
        type_suffix = f":{content_type}" if content_type else ""
        return f"search:{self._hash_key(keyword)}{type_suffix}"

    async def get_search_result(
        self,
        keyword: str,
        content_type: Optional[str] = None
    ) -> Optional[List[int]]:
        """获取搜索结果缓存（内容 ID 列表）"""
        data = await self.get_json(self._search_key(keyword, content_type))
        return data if isinstance(data, list) else None

    async def set_search_result(
        self,
        keyword: str,
        content_ids: List[int],
        content_type: Optional[str] = None
    ) -> bool:
        """设置搜索结果缓存"""
        return await self.set_json(
            self._search_key(keyword, content_type),
            content_ids,
            self.config.search_ttl
        )

    # =====================================================
    # 缓存失效
    # =====================================================

    async def invalidate_content_cache(
        self,
        content_id: int,
        content_type: str,
        category_id: int,
        artist_ids: Optional[List[int]] = None,
        tag_ids: Optional[List[int]] = None
    ) -> None:
        """
        内容更新时清除相关缓存

        Args:
            content_id: 内容 ID
            content_type: 内容类型
            category_id: 分类 ID
            artist_ids: 关联的艺术家 ID 列表
            tag_ids: 关联的标签 ID 列表
        """
        keys_to_delete = [
            self._content_key(content_id),
            self._content_list_key(content_type, category_id),
            self._content_hot_key(content_type),
        ]

        # 清除艺术家相关缓存
        if artist_ids:
            for artist_id in artist_ids:
                keys_to_delete.append(self._artist_contents_key(artist_id))

        # 清除标签相关缓存
        if tag_ids:
            for tag_id in tag_ids:
                keys_to_delete.append(self._tag_contents_key(tag_id))

        await self.delete(*keys_to_delete)
        logger.debug(f"Invalidated cache for content {content_id}")

    async def clear_all_cache(self) -> None:
        """清除所有缓存（谨慎使用）"""
        await self.client.flushdb()
        logger.warning("All Redis cache cleared")

    # =====================================================
    # 健康检查
    # =====================================================

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            await self.client.ping()
            info = await self.client.info("memory")
            return {
                "status": "healthy",
                "connected": True,
                "used_memory": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
            }


# 全局实例
_redis_service: Optional[RedisService] = None


async def get_redis_service() -> RedisService:
    """获取 Redis 服务实例"""
    global _redis_service
    if _redis_service is None:
        raise RuntimeError("Redis service not initialized")
    return _redis_service


async def init_redis_service(config: RedisConfig) -> RedisService:
    """初始化 Redis 服务"""
    global _redis_service
    _redis_service = RedisService(config)
    await _redis_service.initialize()
    return _redis_service


async def close_redis_service() -> None:
    """关闭 Redis 服务"""
    global _redis_service
    if _redis_service:
        await _redis_service.close()
        _redis_service = None
