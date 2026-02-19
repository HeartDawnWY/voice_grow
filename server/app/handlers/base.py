"""
处理器基类和响应数据类
"""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from ..core.nlu import NLUResult
from ..core.tts import TTSService
from ..models.database import ContentType
from ..services.content_service import ContentService

logger = logging.getLogger(__name__)


@dataclass
class HandlerResponse:
    """处理器响应"""
    # 响应文本 (用于 TTS)
    text: str

    # 播放 URL (可选，用于播放音频内容)
    play_url: Optional[str] = None

    # 内容信息 (可选)
    content_info: Optional[Dict[str, Any]] = None

    # 是否需要继续监听
    continue_listening: bool = False

    # 额外命令
    commands: List[str] = None

    # 播放队列状态: True=启用自动续播, False=关闭, None=不改变当前状态
    queue_active: Optional[bool] = None

    # 跳过中断: True 时 respond() 不发送 abort_xiaoai + pause（用于音量/继续播放）
    skip_interrupt: bool = False

    def __post_init__(self):
        if self.commands is None:
            self.commands = []


class BaseHandler(ABC):
    """处理器基类"""

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService,
        play_queue_service=None,
    ):
        self.content_service = content_service
        self.tts_service = tts_service
        self.play_queue_service = play_queue_service

    @abstractmethod
    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理意图"""
        pass

    async def safe_handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """模板方法：统一错误处理"""
        try:
            return await self.handle(nlu_result, device_id, context)
        except Exception as e:
            logger.error(f"{self.__class__.__name__} 处理失败: {e}", exc_info=True)
            return HandlerResponse(text="抱歉，服务暂时不可用，请稍后再试")

    async def _infer_category_id(
        self,
        keyword: str,
        artist_name: str,
        title: str,
        content_type: ContentType,
    ) -> Optional[int]:
        """两级策略推断内容分类：关键词匹配 → LLM 推断

        只匹配 DB 中已有的活跃分类，不新建分类。
        需要子类持有 self.llm_service 才能使用 Level 2。
        返回 None 表示无法推断。
        """
        categories = await self.content_service.list_active_categories(content_type)
        if not categories:
            return None

        # --- Level 1: 关键词匹配（要求匹配长度 >= 2 避免单字误匹配） ---
        search_texts = [keyword, artist_name, title]
        for text in search_texts:
            if not text or len(text) < 2:
                continue
            for cat in categories:
                cat_name = cat["name"]
                if len(cat_name) < 2:
                    continue
                if cat_name in text or text in cat_name:
                    logger.info(f"分类关键词匹配: '{text}' → '{cat_name}' (id={cat['id']})")
                    return cat["id"]

        # --- Level 2: LLM 推断 ---
        llm_service = getattr(self, "llm_service", None)
        if not llm_service:
            return None

        cat_list_str = "、".join(f"{c['name']}(id={c['id']})" for c in categories)
        desc = f"歌手: {artist_name}" if artist_name else ""
        if title:
            label = "歌名" if content_type == ContentType.MUSIC else "名称"
            desc += f"{'，' if desc else ''}{label}: {title}"

        resp = None
        try:
            result = await llm_service.chat_with_details(
                message=(
                    f"以下内容应该归入哪个分类？只回复分类ID数字，不要其他内容。\n"
                    f"{desc}\n"
                    f"可选分类: {cat_list_str}"
                ),
                system_message="你是内容分类专家。根据内容信息选择最合适的分类，只回复分类ID数字。",
                temperature=0.1,
                max_tokens=20,
            )
            resp = result.response
            match = re.search(r'\d+', resp)
            if match:
                cat_id = int(match.group())
                valid_ids = {c["id"] for c in categories}
                if cat_id in valid_ids:
                    logger.info(f"LLM分类推断: '{keyword}' → id={cat_id}")
                    return cat_id
                logger.warning(f"LLM返回无效分类ID: {cat_id}, 有效范围: {valid_ids}")
            else:
                logger.warning(f"LLM分类推断无数字: resp='{resp}'")
        except Exception as e:
            logger.warning(f"LLM分类推断调用失败: {e}")

        return None
