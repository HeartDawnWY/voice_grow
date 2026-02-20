"""
故事播放处理器
"""

import asyncio
import hashlib
import logging
import time
from typing import Optional, Dict, TYPE_CHECKING

import httpx
from pypinyin import lazy_pinyin
from ..core.nlu import Intent, NLUResult
from ..core.tts import TTSService
from ..core.llm import LLMService, ContentFilter
from ..models.database import ContentType
from ..services.content_service import ContentService
from .base import BaseHandler, HandlerResponse

if TYPE_CHECKING:
    from ..services.download_service import DownloadService

logger = logging.getLogger(__name__)

# 故事名称最大长度（防止超长输入注入）
_MAX_STORY_NAME_LENGTH = 50

STORY_SYSTEM_PROMPT = (
    "你是一位儿童故事作家，专门为3-10岁儿童创作故事。"
    "故事要温暖、有趣、积极向上，语言简单易懂。"
)

STORY_GENERATION_PROMPT = (
    '请创作一个关于"{story_name}"的儿童故事。\n'
    "要求：\n"
    "1. 长度500-800字，适合语音播放（约3-5分钟）\n"
    "2. 有开头、发展和结尾\n"
    "3. 语言生动有趣\n"
    "4. 直接输出故事内容，不要标题和多余说明"
)


class StoryHandler(BaseHandler):
    """故事播放处理器"""

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService,
        llm_service: LLMService,
        play_queue_service=None,
        download_service: Optional["DownloadService"] = None,
    ):
        super().__init__(content_service, tts_service, play_queue_service)
        self.llm_service = llm_service
        self.download_service = download_service
        self._ai_category_id: Optional[int] = None
        self._category_lock = asyncio.Lock()
        self._content_filter = ContentFilter()

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

        if intent == Intent.PLAY_STORY:
            content = await self.content_service.get_random_story()

        elif intent == Intent.PLAY_STORY_CATEGORY:
            category = slots.get("category")
            content = await self.content_service.get_random_story(category)

        elif intent == Intent.PLAY_STORY_BY_NAME:
            name = slots.get("story_name")
            if name:
                content = await self.content_service.get_content_by_name(
                    ContentType.STORY, name
                )
                if not content:
                    # 先尝试在线搜索，搜不到再 AI 生成
                    content = await self._search_online_story(name, device_id, context)
                if not content:
                    content = await self._generate_story(name, device_id, context)

        if content:
            if content.get("id"):
                await self.content_service.increment_play_count(content["id"])

            # 清空旧播放队列
            if self.play_queue_service:
                await self.play_queue_service.clear_queue(device_id)

            return HandlerResponse(
                text=f"好的，给你讲{content['title']}",
                play_url=content["play_url"],
                content_info=content
            )
        else:
            return HandlerResponse(
                text="抱歉，没有找到你想听的故事，换一个试试吧"
            )

    async def _search_online_story(
        self,
        name: str,
        device_id: str,
        context: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """在线搜索故事，返回内容字典或 None"""
        if not self.download_service:
            return None

        keyword = f"{name} 故事"

        play_tts = context.get("play_tts") if context else None
        play_url_fn = context.get("play_url") if context else None

        # 1. 播报搜索提示
        prompt_text = f"正在搜索{name}的故事，请稍等"
        if play_tts:
            await play_tts(prompt_text)
            wait_seconds = len(prompt_text) * 0.25 + 0.5
            await asyncio.sleep(wait_seconds)

        # 2. 播放背景轻音乐
        if play_url_fn:
            try:
                bgm = await self.content_service.get_random_music("轻音乐")
                if bgm and bgm.get("play_url"):
                    await play_url_fn(bgm["play_url"])
            except Exception:
                pass

        # 3. 执行搜索下载 — 推断分类而非使用"在线搜索"伪分类
        try:
            category_id = await self._infer_category_id(
                keyword, "", name, ContentType.STORY
            )
            if not category_id:
                cats = await self.content_service.list_active_categories(ContentType.STORY)
                if cats:
                    # 优先选子分类（level>1），避免退化到根分类"故事"
                    default_cat = next((c for c in cats if c["level"] > 1), cats[0])
                    category_id = default_cat["id"]
                    logger.warning(f"分类推断失败，使用默认分类: id={category_id}, name='{default_cat['name']}'")
            if not category_id:
                logger.warning("无可用分类，跳过在线下载")
                return None
            content_id = await self.download_service.search_and_download(
                keyword=keyword,
                content_type="story",
                category_id=category_id,
                artist_type="narrator",
            )
        except Exception as e:
            logger.error(f"在线搜索故事失败: keyword='{keyword}', error={e}", exc_info=True)
            return None

        if not content_id:
            return None

        # 4. 从 DB 获取内容
        try:
            content = await self.content_service.get_content_by_id(content_id)
            if content and content.get("play_url"):
                logger.info(f"在线故事下载成功: id={content_id}, title='{content.get('title')}'")
                return content
        except Exception as e:
            logger.error(f"获取下载故事内容失败: content_id={content_id}, error={e}")

        return None

    async def _generate_story(
        self,
        name: str,
        device_id: str,
        context: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        LLM 生成故事 fallback

        DB 中未找到指定故事时：
        1. 输入安全检查
        2. 播报"正在创作"提示
        3. 播放背景轻音乐（等待期间）
        4. LLM 生成故事文本 + 内容安全过滤
        5. TTS 合成音频 → 持久化到 MinIO
        6. 写入 DB（下次直接命中）
        """
        # Fix #2: 输入清洗 — 长度限制 + 安全检查
        name = name[:_MAX_STORY_NAME_LENGTH]
        if not self._content_filter.is_safe(name):
            logger.warning(f"故事名称未通过安全检查: {name[:20]}")
            return None

        play_tts = context.get("play_tts") if context else None
        play_url_fn = context.get("play_url") if context else None

        # 1. 播报"正在创作" + 等待播完后播放背景轻音乐
        prompt_text = f"网上也没有找到{name}的故事，正在为你创作，请稍等" if self.download_service else f"没有找到{name}的故事，正在为你创作，请稍等"
        if play_tts:
            await play_tts(prompt_text)
            # 等待提示语播完再发下一个 play_url（音箱是替换式播放）
            wait_seconds = len(prompt_text) * 0.25 + 0.5
            await asyncio.sleep(wait_seconds)

        # 2. 播放背景轻音乐（等待期间）
        if play_url_fn:
            try:
                bgm = await self.content_service.get_random_music("轻音乐")
                if bgm and bgm.get("play_url"):
                    await play_url_fn(bgm["play_url"])
            except Exception:
                pass  # 背景音乐播放失败不影响主流程

        # Fix #1: 整体 try/except，失败时 fallback 到"没有找到"提示
        try:
            # 3. LLM 生成故事
            logger.info(f"开始生成故事: name='{name}', device={device_id}")
            story_text = await self.llm_service.chat(
                STORY_GENERATION_PROMPT.format(story_name=name),
                system_message=STORY_SYSTEM_PROMPT,
                max_tokens=1500,
            )

            # Fix #3: 对 LLM 输出做内容安全过滤（仅检查关键词，不截断长文本）
            if not self._content_filter.is_safe(story_text):
                logger.warning(f"LLM 生成的故事未通过安全过滤: {name}")
                return None

            # 4. TTS 合成
            audio_url = await self.tts_service.synthesize_to_url(story_text)

            # Fix #6: 下载 TTS 音频并持久化到自有 MinIO（防止外部 URL 过期）
            minio_path = await self._persist_audio(name, audio_url)

            # 5. 写入 DB（失败不影响播放）
            try:
                category_id = await self._get_ai_category_id()
                title_pinyin = "".join(lazy_pinyin(name))
                await self.content_service.create_content(
                    content_type=ContentType.STORY,
                    category_id=category_id,
                    title=name,
                    title_pinyin=title_pinyin,
                    minio_path=minio_path,
                    description=story_text,
                )
            except Exception as e:
                logger.warning(f"保存生成故事失败: {e}")

            return {"title": name, "play_url": audio_url}

        except Exception as e:
            logger.error(f"生成故事失败: name='{name}', error={e}", exc_info=True)
            return None

    async def _persist_audio(self, name: str, audio_url: str) -> str:
        """
        下载 TTS 音频并上传到自有 MinIO，返回对象路径。

        失败时降级为直接存储原始 URL。
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(audio_url)
                resp.raise_for_status()
                audio_bytes = resp.content

            name_hash = hashlib.md5(name.encode()).hexdigest()[:8]
            ts = int(time.time())
            object_name = f"stories/ai_generated/{name_hash}_{ts}.mp3"

            await self.content_service.minio.upload_bytes(
                audio_bytes, object_name, content_type="audio/mpeg"
            )
            logger.info(f"AI 故事音频已上传 MinIO: {object_name}")
            return object_name
        except Exception as e:
            logger.warning(f"音频持久化失败，使用原始 URL: {e}")
            return audio_url

    async def _get_ai_category_id(self) -> int:
        """获取或创建 'AI生成' 故事分类 ID（结果缓存，带锁防并发重复创建）"""
        if self._ai_category_id is not None:
            return self._ai_category_id

        async with self._category_lock:
            if self._ai_category_id is not None:
                return self._ai_category_id
            self._ai_category_id = await self.content_service.get_or_create_category(
                "AI生成", ContentType.STORY, "LLM 自动生成的故事"
            )

        return self._ai_category_id
