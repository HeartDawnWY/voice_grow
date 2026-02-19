"""
音乐播放处理器
"""

import asyncio
import logging
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

from ..core.nlu import Intent, NLUResult
from ..core.tts import TTSService
from ..core.llm import LLMService
from ..models.database import ContentType
from ..services.content_service import ContentService
from .base import BaseHandler, HandlerResponse

if TYPE_CHECKING:
    from ..services.download_service import DownloadService

logger = logging.getLogger(__name__)


class MusicHandler(BaseHandler):
    """音乐播放处理器"""

    def __init__(
        self,
        content_service: ContentService,
        tts_service: TTSService,
        play_queue_service=None,
        download_service: Optional["DownloadService"] = None,
        llm_service: Optional[LLMService] = None,
    ):
        super().__init__(content_service, tts_service, play_queue_service)
        self.download_service = download_service
        self.llm_service = llm_service

    async def _setup_queue(
        self, results: List[Dict], device_id: str
    ) -> Tuple[Optional[Dict], int]:
        """过滤可播放内容并设置播放队列

        Returns:
            (首条内容, 入队数量)
        """
        playable = [r for r in results if r.get("play_url")]
        if not playable:
            return None, 0
        content = playable[0]
        queued_count = 0
        if self.play_queue_service and len(playable) > 1:
            content_ids = [r["id"] for r in playable]
            await self.play_queue_service.set_queue(device_id, content_ids, start_index=0)
            queued_count = len(playable)
        return content, queued_count

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
        queued_count = 0
        category_label = ""

        if intent == Intent.PLAY_MUSIC:
            results = await self.content_service.get_content_list(
                ContentType.MUSIC, limit=30, shuffle=True
            )
            content, queued_count = await self._setup_queue(results, device_id)

        elif intent == Intent.PLAY_MUSIC_CATEGORY:
            category = slots.get("category")
            if not category:
                return HandlerResponse(text="请告诉我你想听什么类型的音乐")
            category_label = category
            results = await self.content_service.get_content_list(
                ContentType.MUSIC, category_name=category, limit=30, shuffle=True
            )
            content, queued_count = await self._setup_queue(results, device_id)

        elif intent == Intent.PLAY_MUSIC_BY_ARTIST:
            artist_name = slots.get("artist_name")
            if artist_name:
                results = await self.content_service.search_by_artist(
                    artist_name, ContentType.MUSIC, limit=20
                )
                if results:
                    content, queued_count = await self._setup_queue(results, device_id)

        elif intent == Intent.PLAY_MUSIC_BY_NAME:
            music_name = slots.get("music_name")
            artist_name = slots.get("artist_name")
            if artist_name and music_name:
                content = await self.content_service.search_by_artist_and_title(
                    artist_name, music_name
                )
            elif music_name:
                content = await self.content_service.get_content_by_name(
                    ContentType.MUSIC, music_name
                )

        # 统一保护：确保内容有音频文件
        if content and not content.get("play_url"):
            logger.warning(f"内容无音频文件，跳过: id={content.get('id')}, title={content.get('title')}")
            content = None

        # DB 未命中时，对按名称/歌手搜索的意图尝试在线搜索下载
        if not content and intent in (Intent.PLAY_MUSIC_BY_NAME, Intent.PLAY_MUSIC_BY_ARTIST):
            artist = slots.get("artist_name", "")
            music = slots.get("music_name", "")
            content = await self._search_and_download_music(
                artist_name=artist, music_name=music,
                device_id=device_id, context=context,
            )

        if content:
            if content.get("id"):
                await self.content_service.increment_play_count(content["id"])

            # 单曲播放时清空旧队列，避免"下一首"跳到陈旧队列
            if self.play_queue_service and queued_count == 0:
                await self.play_queue_service.clear_queue(device_id)

            # 构建响应文本
            if queued_count > 1:
                if intent == Intent.PLAY_MUSIC_BY_ARTIST:
                    artist_name = slots.get("artist_name", "")
                    response_text = f"找到{artist_name}的{queued_count}首歌，先为你播放{content['title']}"
                elif intent == Intent.PLAY_MUSIC_CATEGORY:
                    response_text = f"为你播放{category_label}，共{queued_count}首，先来一首{content['title']}"
                else:
                    response_text = f"为你随机播放音乐，共{queued_count}首，先来一首{content['title']}"
            else:
                response_text = f"为你播放{content['title']}"

            return HandlerResponse(
                text=response_text,
                play_url=content["play_url"],
                content_info=content,
                queue_active=queued_count > 1,
            )
        else:
            if intent in (Intent.PLAY_MUSIC, Intent.PLAY_MUSIC_CATEGORY):
                hint = f"{category_label}分类" if category_label else "音乐"
                return HandlerResponse(
                    text=f"抱歉，{hint}暂时没有内容，你可以在管理后台添加"
                )
            artist = slots.get("artist_name", "")
            music = slots.get("music_name", "")
            hint = f"{artist}的{music}" if artist and music else artist or music or "这首歌"
            return HandlerResponse(
                text=f"抱歉，没有在网上找到{hint}"
            )

    async def _search_and_download_music(
        self,
        artist_name: str,
        music_name: str,
        device_id: str,
        context: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """在线搜索并下载音乐，返回内容字典或 None"""
        if not self.download_service:
            return None

        keyword = f"{artist_name} {music_name}".strip() if artist_name else music_name
        if not keyword:
            return None

        hint = f"{artist_name}的{music_name}" if artist_name and music_name else keyword

        play_tts = context.get("play_tts") if context else None
        play_url_fn = context.get("play_url") if context else None

        # 1. 播报搜索提示
        prompt_text = f"正在网上搜索{hint}，请稍等"
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

        # 3. 执行搜索下载
        #    优先复用歌手历史分类 → 关键词/LLM 推断 → 兜底首个分类
        try:
            category_id = None
            if artist_name:
                category_id = await self.content_service.get_artist_primary_category(
                    artist_name, ContentType.MUSIC
                )
            if not category_id:
                category_id = await self._infer_category_id(
                    keyword, artist_name, music_name, ContentType.MUSIC
                )
            if not category_id:
                cats = await self.content_service.list_active_categories(ContentType.MUSIC)
                if cats:
                    category_id = cats[0]["id"]
                    logger.warning(f"分类推断失败，使用默认分类: id={category_id}, name='{cats[0]['name']}'")
            if not category_id:
                logger.warning("无可用分类，跳过在线下载")
                return None
            content_id = await self.download_service.search_and_download(
                keyword=keyword,
                content_type="music",
                category_id=category_id,
                artist_name=artist_name or None,
                artist_type="singer",
            )
        except Exception as e:
            logger.error(f"在线搜索下载音乐失败: keyword='{keyword}', error={e}", exc_info=True)
            return None

        if not content_id:
            return None

        # 4. 从 DB 获取内容
        try:
            content = await self.content_service.get_content_by_id(content_id)
            if content and content.get("play_url"):
                return content
        except Exception as e:
            logger.error(f"获取下载内容失败: content_id={content_id}, error={e}")

        return None
