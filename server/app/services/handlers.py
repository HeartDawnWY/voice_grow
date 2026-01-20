"""
意图处理器

处理各种用户意图，生成响应
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List

from ..core.nlu import Intent, NLUResult
from ..core.tts import TTSService
from ..core.llm import LLMService, ChatMessage
from ..models.database import ContentType
from .content_service import ContentService
from .session_service import SessionService

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

    def __post_init__(self):
        if self.commands is None:
            self.commands = []


class BaseHandler(ABC):
    """处理器基类"""

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService
    ):
        self.content_service = content_service
        self.tts_service = tts_service

    @abstractmethod
    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """
        处理意图

        Args:
            nlu_result: NLU 识别结果
            device_id: 设备 ID
            context: 上下文信息

        Returns:
            处理器响应
        """
        pass


class StoryHandler(BaseHandler):
    """故事播放处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理故事相关意图"""
        intent = nlu_result.intent
        slots = nlu_result.slots

        content = None

        # 根据意图获取内容
        if intent == Intent.PLAY_STORY:
            # 播放随机故事
            content = await self.content_service.get_random_story()

        elif intent == Intent.PLAY_STORY_CATEGORY:
            # 按分类播放
            category = slots.get("category")
            content = await self.content_service.get_random_story(category)

        elif intent == Intent.PLAY_STORY_BY_NAME:
            # 按名称播放
            name = slots.get("story_name")
            if name:
                content = await self.content_service.get_content_by_name(
                    ContentType.STORY, name
                )

        if content:
            # 记录播放
            await self.content_service.increment_play_count(content["id"])

            return HandlerResponse(
                text=f"好的，给你讲{content['title']}",
                play_url=content["play_url"],
                content_info=content
            )
        else:
            return HandlerResponse(
                text="抱歉，没有找到你想听的故事，换一个试试吧"
            )


class MusicHandler(BaseHandler):
    """音乐播放处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理音乐相关意图"""
        intent = nlu_result.intent
        slots = nlu_result.slots

        content = None

        if intent == Intent.PLAY_MUSIC:
            # 播放随机音乐
            content = await self.content_service.get_random_music()

        elif intent == Intent.PLAY_MUSIC_CATEGORY:
            # 按分类播放
            category = slots.get("category")
            content = await self.content_service.get_random_music(category)

        elif intent == Intent.PLAY_MUSIC_BY_NAME:
            # 按名称播放
            name = slots.get("music_name")
            if name:
                content = await self.content_service.get_content_by_name(
                    ContentType.MUSIC, name
                )

        if content:
            await self.content_service.increment_play_count(content["id"])

            return HandlerResponse(
                text=f"为你播放{content['title']}",
                play_url=content["play_url"],
                content_info=content
            )
        else:
            return HandlerResponse(
                text="抱歉，没有找到你想听的歌，换一首试试吧"
            )


class EnglishHandler(BaseHandler):
    """英语学习处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理英语学习相关意图"""
        intent = nlu_result.intent
        slots = nlu_result.slots

        if intent == Intent.ENGLISH_LEARN:
            # 开始英语学习
            word_info = await self.content_service.get_random_word(level="basic")
            if word_info:
                return await self._build_word_response(word_info)
            else:
                return HandlerResponse(text="英语学习功能暂时不可用，稍后再试吧")

        elif intent == Intent.ENGLISH_WORD:
            # 查询单词
            word = slots.get("word", "")
            word_info = await self.content_service.get_word(word)
            if word_info:
                return await self._build_word_response(word_info)
            else:
                return HandlerResponse(
                    text=f"抱歉，我不知道{word}用英语怎么说"
                )

        elif intent == Intent.ENGLISH_FOLLOW:
            # 跟读
            word = slots.get("word", "")
            return HandlerResponse(
                text=f"请跟我读：{word}",
                continue_listening=True
            )

        return HandlerResponse(text="我们来学英语吧！")

    async def _build_word_response(self, word_info: Dict) -> HandlerResponse:
        """构建单词响应"""
        word = word_info["word"]
        translation = word_info["translation"]
        phonetic = word_info.get("phonetic", "")

        text = f"{translation}的英语是{word}"
        if phonetic:
            text += f"，读作{phonetic}"

        # 如果有发音音频，使用音频
        audio_url = word_info.get("audio_us_url")

        return HandlerResponse(
            text=text,
            play_url=audio_url,
            content_info=word_info
        )


class ChatHandler(BaseHandler):
    """对话处理器"""

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService,
        llm_service: LLMService,
        session_service: Optional[SessionService] = None
    ):
        super().__init__(content_service, tts_service)
        self.llm_service = llm_service
        self.session_service = session_service

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理对话意图"""
        user_message = nlu_result.raw_text

        # 从 Redis 获取对话历史
        history = []
        if self.session_service:
            history_data = await self.session_service.get_conversation_context(device_id, limit=10)
            history = [ChatMessage(role=msg["role"], content=msg["content"]) for msg in history_data]

        # 调用 LLM
        response = await self.llm_service.chat(user_message, history)

        # 保存对话到 Redis
        if self.session_service:
            await self.session_service.add_to_conversation(device_id, "user", user_message)
            await self.session_service.add_to_conversation(device_id, "assistant", response)

        return HandlerResponse(text=response)

    async def clear_history(self, device_id: str):
        """清除对话历史"""
        if self.session_service:
            await self.session_service.clear_conversation(device_id)


class ControlHandler(BaseHandler):
    """播放控制处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理播放控制意图"""
        intent = nlu_result.intent

        # 控制命令映射
        command_map = {
            Intent.CONTROL_PAUSE: ("pause", "已暂停"),
            Intent.CONTROL_RESUME: ("play", "继续播放"),
            Intent.CONTROL_STOP: ("pause", "已停止"),
            Intent.CONTROL_NEXT: ("next", "好的，下一个"),
            Intent.CONTROL_PREVIOUS: ("previous", "好的，上一个"),
            Intent.CONTROL_VOLUME_UP: ("volume_up", "好的，大声一点"),
            Intent.CONTROL_VOLUME_DOWN: ("volume_down", "好的，小声一点"),
        }

        if intent in command_map:
            command, text = command_map[intent]
            return HandlerResponse(
                text=text,
                commands=[command]
            )

        return HandlerResponse(text="好的")


class SystemHandler(BaseHandler):
    """系统功能处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理系统功能意图"""
        intent = nlu_result.intent

        if intent == Intent.SYSTEM_TIME:
            now = datetime.now()
            time_str = now.strftime("%H点%M分")
            date_str = now.strftime("%m月%d日")
            weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            weekday_str = weekday[now.weekday()]

            return HandlerResponse(
                text=f"现在是{date_str} {weekday_str} {time_str}"
            )

        return HandlerResponse(text="这个功能暂时不支持")


class HandlerRouter:
    """
    处理器路由

    根据意图分发到相应的处理器
    """

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService,
        llm_service: LLMService,
        session_service: Optional[SessionService] = None
    ):
        # 初始化各处理器
        self.story_handler = StoryHandler(content_service, tts_service)
        self.music_handler = MusicHandler(content_service, tts_service)
        self.english_handler = EnglishHandler(content_service, tts_service)
        self.chat_handler = ChatHandler(content_service, tts_service, llm_service, session_service)
        self.control_handler = ControlHandler(content_service, tts_service)
        self.system_handler = SystemHandler(content_service, tts_service)

        # 意图到处理器的映射
        self._intent_map = {
            # 故事
            Intent.PLAY_STORY: self.story_handler,
            Intent.PLAY_STORY_CATEGORY: self.story_handler,
            Intent.PLAY_STORY_BY_NAME: self.story_handler,

            # 音乐
            Intent.PLAY_MUSIC: self.music_handler,
            Intent.PLAY_MUSIC_CATEGORY: self.music_handler,
            Intent.PLAY_MUSIC_BY_NAME: self.music_handler,

            # 播放控制
            Intent.CONTROL_PAUSE: self.control_handler,
            Intent.CONTROL_RESUME: self.control_handler,
            Intent.CONTROL_STOP: self.control_handler,
            Intent.CONTROL_NEXT: self.control_handler,
            Intent.CONTROL_PREVIOUS: self.control_handler,
            Intent.CONTROL_VOLUME_UP: self.control_handler,
            Intent.CONTROL_VOLUME_DOWN: self.control_handler,

            # 英语学习
            Intent.ENGLISH_LEARN: self.english_handler,
            Intent.ENGLISH_WORD: self.english_handler,
            Intent.ENGLISH_FOLLOW: self.english_handler,

            # 对话
            Intent.CHAT: self.chat_handler,

            # 系统
            Intent.SYSTEM_TIME: self.system_handler,
        }

    async def route(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """
        路由到相应处理器

        Args:
            nlu_result: NLU 识别结果
            device_id: 设备 ID
            context: 上下文

        Returns:
            处理器响应
        """
        intent = nlu_result.intent

        handler = self._intent_map.get(intent)
        if handler:
            logger.info(f"路由: {intent.value} -> {handler.__class__.__name__}")
            return await handler.handle(nlu_result, device_id, context)

        # 默认使用对话处理器
        logger.warning(f"未知意图: {intent.value}, 使用对话处理器")
        return await self.chat_handler.handle(nlu_result, device_id, context)
