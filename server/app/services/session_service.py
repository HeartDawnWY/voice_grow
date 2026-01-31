"""
会话管理服务

使用 Redis 存储设备会话状态和对话上下文
"""

import json
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict

from ..config import RedisConfig

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """设备会话状态"""
    device_id: str
    current_content_id: Optional[int] = None
    current_content_type: Optional[str] = None
    playing_position: int = 0  # 播放位置 (秒)
    is_playing: bool = False
    volume: int = 50  # 0-100


@dataclass
class ConversationMessage:
    """对话消息"""
    role: str  # user, assistant
    content: str
    timestamp: float


class SessionService:
    """
    会话管理服务

    使用 Redis 管理:
    - 设备会话状态 (当前播放内容、播放位置等)
    - 对话上下文 (用于 LLM 多轮对话)
    - 播放历史 (用于"继续播放"功能)
    """

    # Redis key 前缀
    KEY_PREFIX = "voicegrow:"
    SESSION_KEY = "session:"
    CONVERSATION_KEY = "conversation:"
    HISTORY_KEY = "history:"

    def __init__(self, config: RedisConfig, redis_client=None):
        """
        初始化会话服务

        Args:
            config: Redis 配置
            redis_client: 已有的 Redis 客户端 (可选，避免重复连接)
        """
        self.config = config
        self._client = redis_client

    async def _get_client(self):
        """获取 Redis 客户端 (懒加载)"""
        if self._client is None:
            import redis.asyncio as redis

            self._client = redis.Redis(
                host=self.config.host,
                port=self.config.port,
                password=self.config.password,
                db=self.config.db,
                decode_responses=True
            )

        return self._client

    def _key(self, prefix: str, device_id: str) -> str:
        """生成 Redis key"""
        return f"{self.KEY_PREFIX}{prefix}{device_id}"

    # ========== 会话状态 ==========

    async def get_session(self, device_id: str) -> Optional[SessionState]:
        """
        获取设备会话状态

        Args:
            device_id: 设备 ID

        Returns:
            SessionState 或 None
        """
        client = await self._get_client()
        key = self._key(self.SESSION_KEY, device_id)

        data = await client.get(key)
        if data:
            try:
                session_dict = json.loads(data)
                return SessionState(**session_dict)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"解析会话数据失败: {e}")
                return None

        return None

    async def update_session(
        self,
        device_id: str,
        **kwargs
    ) -> SessionState:
        """
        更新设备会话状态

        Args:
            device_id: 设备 ID
            **kwargs: 要更新的字段

        Returns:
            更新后的 SessionState
        """
        # 获取现有会话或创建新会话
        session = await self.get_session(device_id)
        if session is None:
            session = SessionState(device_id=device_id)

        # 更新字段
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        # 保存到 Redis
        client = await self._get_client()
        key = self._key(self.SESSION_KEY, device_id)
        ttl = self.config.session_ttl if self.config.session_ttl > 0 else None
        await client.set(
            key,
            json.dumps(asdict(session)),
            ex=ttl
        )

        logger.debug(f"更新会话: {device_id}, {kwargs}")
        return session

    async def delete_session(self, device_id: str):
        """删除设备会话"""
        client = await self._get_client()
        key = self._key(self.SESSION_KEY, device_id)
        await client.delete(key)
        logger.debug(f"删除会话: {device_id}")

    # ========== 对话上下文 ==========

    async def get_conversation_context(
        self,
        device_id: str,
        limit: int = 10
    ) -> List[Dict[str, str]]:
        """
        获取对话上下文

        Args:
            device_id: 设备 ID
            limit: 返回的消息数量

        Returns:
            对话消息列表 [{"role": "user", "content": "..."}, ...]
        """
        client = await self._get_client()
        key = self._key(self.CONVERSATION_KEY, device_id)

        # 获取最近的消息
        messages = await client.lrange(key, -limit, -1)

        result = []
        for msg in messages:
            try:
                data = json.loads(msg)
                result.append({
                    "role": data["role"],
                    "content": data["content"]
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return result

    async def add_to_conversation(
        self,
        device_id: str,
        role: str,
        content: str
    ):
        """
        添加消息到对话上下文

        Args:
            device_id: 设备 ID
            role: 角色 (user/assistant)
            content: 消息内容
        """
        import time

        client = await self._get_client()
        key = self._key(self.CONVERSATION_KEY, device_id)

        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=time.time()
        )

        # 添加到列表末尾
        await client.rpush(key, json.dumps(asdict(message)))

        # 限制列表长度 (保留最近 50 条)
        await client.ltrim(key, -50, -1)

        # 设置过期时间
        if self.config.session_ttl > 0:
            await client.expire(key, self.config.session_ttl)

        logger.debug(f"添加对话: {device_id}, role={role}")

    async def clear_conversation(self, device_id: str):
        """清除对话上下文"""
        client = await self._get_client()
        key = self._key(self.CONVERSATION_KEY, device_id)
        await client.delete(key)
        logger.debug(f"清除对话: {device_id}")

    # ========== 播放历史 ==========

    async def add_to_history(
        self,
        device_id: str,
        content_id: int,
        content_type: str,
        position: int = 0
    ):
        """
        添加到播放历史

        Args:
            device_id: 设备 ID
            content_id: 内容 ID
            content_type: 内容类型
            position: 播放位置 (秒)
        """
        import time

        client = await self._get_client()
        key = self._key(self.HISTORY_KEY, device_id)

        history_item = {
            "content_id": content_id,
            "content_type": content_type,
            "position": position,
            "timestamp": time.time()
        }

        # 添加到列表头部
        await client.lpush(key, json.dumps(history_item))

        # 限制历史长度 (保留最近 100 条)
        await client.ltrim(key, 0, 99)

        # 设置过期时间 (7 天)
        await client.expire(key, 7 * 24 * 3600)

    async def get_history(
        self,
        device_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取播放历史

        Args:
            device_id: 设备 ID
            limit: 返回数量

        Returns:
            播放历史列表
        """
        client = await self._get_client()
        key = self._key(self.HISTORY_KEY, device_id)

        items = await client.lrange(key, 0, limit - 1)

        result = []
        for item in items:
            try:
                result.append(json.loads(item))
            except json.JSONDecodeError:
                continue

        return result

    async def get_last_played(
        self,
        device_id: str,
        content_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取最近播放的内容

        Args:
            device_id: 设备 ID
            content_type: 内容类型过滤 (可选)

        Returns:
            最近播放的内容信息
        """
        history = await self.get_history(device_id, limit=20)

        for item in history:
            if content_type is None or item.get("content_type") == content_type:
                return item

        return None

    # ========== 工具方法 ==========

    async def ping(self) -> bool:
        """测试 Redis 连接"""
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            return False

    async def close(self):
        """关闭 Redis 连接"""
        if self._client:
            await self._client.close()
            self._client = None
