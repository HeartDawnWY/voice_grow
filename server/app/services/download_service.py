"""
多平台内容下载服务

从 yt-dlp 支持的平台下载音频，转换为 M4A，上传至 MinIO 并创建 DB 记录
支持多平台关键字搜索、质量排序、标题去重、批量下载
"""

import asyncio
import hashlib
import logging
import math
import os
import re
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .redis_service import RedisService

import httpx
from pypinyin import lazy_pinyin

from ..models.database import ArtistType, ContentType
from .content_service import ContentService
from .minio_service import MinIOService

logger = logging.getLogger(__name__)

MAX_CONCURRENT_DOWNLOADS = 3

DOWNLOAD_CACHE_TTL    = 7  * 86400   # 7天：下载结果缓存
TRANSLATION_CACHE_TTL = 30 * 86400   # 30天：翻译结果缓存（翻译不会变）
PLATFORM_BONUS = {"bilibili": 8, "youtube": 3, "soundcloud": 0}


# ========== 数据结构 ==========

class TaskStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING_INFO = "extracting_info"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    CREATING_RECORD = "creating_record"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


@dataclass
class TrackProgress:
    index: int
    title: str
    status: str = "pending"       # pending, downloading, uploading, completed, failed
    error: Optional[str] = None
    content_id: Optional[int] = None


@dataclass
class DownloadTask:
    task_id: str
    url: str
    params: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    tracks: List[TrackProgress] = field(default_factory=list)
    completed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "status": self.status.value,
            "tracks": [
                {
                    "index": t.index,
                    "title": t.title,
                    "status": t.status,
                    "error": t.error,
                    "content_id": t.content_id,
                }
                for t in self.tracks
            ],
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
            "error": self.error,
            "created_at": self.created_at,
        }


class DownloadTaskManager:
    """任务管理器 (内存存储)"""

    def __init__(self):
        self._tasks: Dict[str, DownloadTask] = {}
        self._async_tasks: Dict[str, asyncio.Task] = {}

    def create(self, url: str, params: dict) -> DownloadTask:
        # 自动清理旧任务
        self.cleanup()
        task_id = str(uuid.uuid4())[:8]
        task = DownloadTask(task_id=task_id, url=url, params=params)
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Optional[DownloadTask]:
        return self._tasks.get(task_id)

    def list_all(self, limit: int = 50) -> List[dict]:
        sorted_tasks = sorted(
            self._tasks.values(), key=lambda t: t.created_at, reverse=True
        )
        return [t.to_dict() for t in sorted_tasks[:limit]]

    def active_count(self) -> int:
        """正在执行的任务数"""
        return sum(
            1 for t in self._tasks.values()
            if t.status not in TERMINAL_STATUSES
        )

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.status in TERMINAL_STATUSES:
            return False
        task.status = TaskStatus.CANCELLED
        async_task = self._async_tasks.get(task_id)
        if async_task and not async_task.done():
            async_task.cancel()
        return True

    def set_async_task(self, task_id: str, async_task: asyncio.Task):
        self._async_tasks[task_id] = async_task

    def get_async_task(self, task_id: str) -> Optional[asyncio.Task]:
        return self._async_tasks.get(task_id)

    def cleanup(self, max_age: float = 86400):
        """清理超过 max_age 秒的已完成任务"""
        now = time.time()
        to_remove = [
            tid
            for tid, t in self._tasks.items()
            if t.status in TERMINAL_STATUSES
            and now - t.created_at > max_age
        ]
        for tid in to_remove:
            del self._tasks[tid]
            self._async_tasks.pop(tid, None)


# ========== Content type mapping ==========

CONTENT_TYPE_MAP = {
    "music": ContentType.MUSIC,
    "story": ContentType.STORY,
    "sound": ContentType.MUSIC,
}

ARTIST_TYPE_MAP = {
    "singer": ArtistType.SINGER,
    "band": ArtistType.BAND,
    "narrator": ArtistType.NARRATOR,
    "author": ArtistType.AUTHOR,
    "composer": ArtistType.COMPOSER,
}

FOLDER_MAP = {
    "music": "music",
    "story": "stories",
    "sound": "music",
}


# ========== 搜索平台配置 ==========

SEARCH_EXTRACTORS = {
    "youtube": {"prefix": "ytsearch", "label": "YouTube"},
    "bilibili": {"prefix": "bilisearch", "label": "Bilibili"},
    "soundcloud": {"prefix": "scsearch", "label": "SoundCloud"},
    "niconico": {"prefix": "nicosearch", "label": "NicoNico"},
}
DEFAULT_PLATFORMS = ["youtube", "bilibili", "soundcloud"]

# 时长偏好范围 (秒)
DURATION_PREFERENCES = {
    "music": (120, 480),     # 2-8 分钟
    "story": (180, 1800),    # 3-30 分钟
    "sound": (60, 600),      # 1-10 分钟
}


# ========== 核心服务 ==========

class DownloadService:
    def __init__(
        self,
        minio_service: MinIOService,
        content_service: ContentService,
        redis_service: Optional["RedisService"] = None,
    ):
        self.minio = minio_service
        self.content_service = content_service
        self.task_manager = DownloadTaskManager()
        self.redis = redis_service

        # yt-dlp 全局选项 (代理 + cookies)
        self._proxy = os.getenv("YTDLP_PROXY", "")
        self._cookies_file = os.getenv("YTDLP_COOKIES_FILE", "")
        if self._proxy:
            logger.info(f"yt-dlp 代理: {self._proxy}")
        if self._cookies_file:
            logger.info(f"yt-dlp cookies: {self._cookies_file}")

    def _base_ydl_opts(self) -> dict:
        """返回 yt-dlp 基础选项（含代理、cookies、JS runtime）"""
        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            # YouTube 需要 deno + EJS 挑战求解器才能正常提取视频
            "remote_components": ["ejs:github"],
        }
        if self._proxy:
            opts["proxy"] = self._proxy
        if self._cookies_file and os.path.isfile(self._cookies_file):
            opts["cookiefile"] = self._cookies_file
        return opts

    def start_download(
        self,
        url: str,
        content_type: str,
        category_id: int,
        artist_name: Optional[str] = None,
        artist_type: str = "singer",
        tag_ids: Optional[List[int]] = None,
        age_min: int = 0,
        age_max: int = 12,
    ) -> DownloadTask:
        """创建下载任务并立即返回"""
        if self.task_manager.active_count() >= MAX_CONCURRENT_DOWNLOADS:
            from ..models.response import BusinessException, ErrorCode
            raise BusinessException(
                ErrorCode.REQUEST_TOO_FREQUENT,
                f"已有 {MAX_CONCURRENT_DOWNLOADS} 个下载任务在执行，请等待完成后再试"
            )

        params = {
            "content_type": content_type,
            "category_id": category_id,
            "artist_name": artist_name,
            "artist_type": artist_type,
            "tag_ids": tag_ids,
            "age_min": age_min,
            "age_max": age_max,
        }
        task = self.task_manager.create(url, params)

        async_task = asyncio.create_task(self._execute_download(task))
        self.task_manager.set_async_task(task.task_id, async_task)

        return task

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        return self.task_manager.get(task_id)

    def list_tasks(self) -> List[dict]:
        return self.task_manager.list_all()

    def cancel_task(self, task_id: str) -> bool:
        return self.task_manager.cancel(task_id)

    # ========== 私有方法：下载流程 ==========

    async def _execute_download(self, task: DownloadTask):
        """完整的下载流程"""
        try:
            # 1. 提取视频信息
            task.status = TaskStatus.EXTRACTING_INFO
            entries = await self._extract_info(task.url)

            if not entries:
                task.status = TaskStatus.FAILED
                task.error = "未找到可下载的视频"
                return

            task.total_count = len(entries)
            task.tracks = [
                TrackProgress(index=i, title=e.get("title", f"Track {i+1}"))
                for i, e in enumerate(entries)
            ]

            # 2. 解析/创建艺术家
            artist_id = await self._resolve_artist(
                entries[0],
                task.params.get("artist_name"),
                task.params.get("artist_type", "singer"),
            )

            # 3. 逐个处理
            task.status = TaskStatus.DOWNLOADING
            for i, entry in enumerate(entries):
                if task.status == TaskStatus.CANCELLED:
                    break

                try:
                    content_id = await self._process_single_track(
                        entry=entry,
                        task=task,
                        track_index=i,
                        artist_id=artist_id,
                    )
                    task.tracks[i].status = "completed"
                    task.tracks[i].content_id = content_id
                    task.completed_count += 1
                except Exception as e:
                    logger.error(f"处理第 {i+1} 首失败: {e}", exc_info=True)
                    task.tracks[i].status = "failed"
                    task.tracks[i].error = str(e)[:200]
                    task.failed_count += 1

            # 4. 最终状态
            if task.status == TaskStatus.CANCELLED:
                return
            if task.completed_count == 0:
                task.status = TaskStatus.FAILED
                task.error = "所有曲目均下载失败"
            else:
                task.status = TaskStatus.COMPLETED

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
        except Exception as e:
            logger.error(f"下载任务失败: {e}", exc_info=True)
            task.status = TaskStatus.FAILED
            # 提取 yt-dlp 错误中的可读信息
            err_msg = str(e)
            if "not available" in err_msg.lower():
                task.error = "视频不可用（可能有地域限制或已被删除）"
            elif "private video" in err_msg.lower():
                task.error = "视频为私有视频，无法访问"
            elif "sign in" in err_msg.lower():
                task.error = "需要登录才能访问，请配置 YTDLP_COOKIES_FILE"
            else:
                task.error = err_msg[:300]

    async def _extract_info(self, url: str) -> List[dict]:
        """提取视频/播放列表信息"""
        import yt_dlp

        ydl_opts = {
            **self._base_ydl_opts(),
            "extract_flat": False,
            "skip_download": True,
        }

        loop = asyncio.get_running_loop()

        def _do_extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    return []
                # 播放列表
                if "entries" in info:
                    return [e for e in info["entries"] if e is not None]
                # 单个视频
                return [info]

        return await loop.run_in_executor(None, _do_extract)

    async def _resolve_artist(
        self,
        entry: dict,
        artist_name: Optional[str],
        artist_type_str: str,
    ) -> Optional[int]:
        """解析或创建艺术家，返回 artist_id"""
        artist_type = ARTIST_TYPE_MAP.get(artist_type_str, ArtistType.SINGER)

        # 确定名称
        if not artist_name:
            artist_name = (
                entry.get("artist")
                or entry.get("uploader")
                or entry.get("channel")
                or "Unknown"
            )

        # 搜索已有 — 分页搜索直到找到精确匹配或全部搜完
        page = 1
        max_pages = 20
        while page <= max_pages:
            result = await self.content_service.list_artists_admin(
                keyword=artist_name, page=page, page_size=50
            )
            items = result.get("items", [])
            for item in items:
                if item.get("name") == artist_name:
                    return item["id"]
            # 没有更多结果
            if not items or page >= result.get("total_pages", 1):
                break
            page += 1

        # 创建新艺术家
        new_artist = await self.content_service.create_artist(
            name=artist_name,
            artist_type=artist_type,
            description="Auto-created from download",
        )
        return new_artist.get("id")

    async def _process_single_track(
        self,
        entry: dict,
        task: DownloadTask,
        track_index: int,
        artist_id: Optional[int],
    ) -> int:
        """下载单个曲目 → 上传 MinIO → 创建 DB 记录 → 返回 content_id"""
        import yt_dlp
        from mutagen.mp4 import MP4

        track = task.tracks[track_index]
        track.status = "downloading"

        video_url = entry.get("webpage_url") or entry.get("url") or entry.get("original_url")
        video_id = entry.get("id", "")
        title = entry.get("title", f"Track {track_index + 1}")
        content_type_str = task.params["content_type"]
        folder = FOLDER_MAP.get(content_type_str, "music")
        content_type = CONTENT_TYPE_MAP.get(content_type_str, ContentType.MUSIC)

        # 生成 MinIO 路径：优先使用 YouTube video ID，否则用 SHA-256 hash
        if video_id:
            file_key = video_id
        else:
            file_key = hashlib.sha256(
                f"{video_url}:{title}".encode()
            ).hexdigest()[:16]

        minio_path = f"{folder}/{file_key}.m4a"

        with tempfile.TemporaryDirectory() as tmpdir:
            # 下载 + 转码 M4A
            output_template = os.path.join(tmpdir, "%(id)s.%(ext)s")
            ydl_opts = {
                **self._base_ydl_opts(),
                "outtmpl": output_template,
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                        "preferredquality": "256",
                    }
                ],
            }

            loop = asyncio.get_running_loop()

            def _do_download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])

            await loop.run_in_executor(None, _do_download)

            # 找到下载的 M4A 文件
            m4a_files = [f for f in os.listdir(tmpdir) if f.endswith(".m4a")]
            if not m4a_files:
                raise RuntimeError(f"M4A 文件未生成: {title}")

            local_path = os.path.join(tmpdir, m4a_files[0])

            # 读取时长
            duration = 0
            try:
                audio = MP4(local_path)
                if audio.info and audio.info.length:
                    duration = int(audio.info.length)
            except Exception as e:
                logger.warning(f"无法读取时长: {e}")

            # 上传 M4A 到 MinIO
            track.status = "uploading"
            await self.minio.upload_file(local_path, minio_path, "audio/mp4")

            # 下载并上传封面 (可选)
            cover_path = ""
            thumbnail_url = entry.get("thumbnail")
            if thumbnail_url:
                try:
                    cover_path = await self._upload_thumbnail(
                        thumbnail_url, file_key
                    )
                except Exception as e:
                    logger.warning(f"封面上传失败: {e}")

        # 创建 DB 记录 (tmpdir 已清理，此处只用变量)
        track.status = "creating_record"
        title_pinyin = "".join(lazy_pinyin(title))

        artist_ids_param = None
        if artist_id:
            artist_ids_param = [
                {"id": artist_id, "role": task.params.get("artist_type", "singer"), "is_primary": True}
            ]

        content = await self.content_service.create_content(
            content_type=content_type,
            category_id=task.params["category_id"],
            title=title,
            minio_path=minio_path,
            title_pinyin=title_pinyin,
            cover_path=cover_path,
            duration=duration,
            age_min=task.params.get("age_min", 0),
            age_max=task.params.get("age_max", 12),
            artist_ids=artist_ids_param,
            tag_ids=task.params.get("tag_ids"),
        )

        return content.get("id", 0)

    async def _upload_thumbnail(self, url: str, file_key: str) -> str:
        """下载缩略图并上传到 MinIO"""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        ext = "jpg"
        ct = resp.headers.get("content-type", "")
        if "png" in ct:
            ext = "png"
        elif "webp" in ct:
            ext = "webp"

        cover_object = f"covers/{file_key}.{ext}"
        content_type_header = ct or "image/jpeg"

        await self.minio.upload_bytes(resp.content, cover_object, content_type_header)
        return cover_object

    # ========== 搜索功能 ==========

    async def search(
        self,
        keyword: str,
        platforms: Optional[List[str]] = None,
        content_type: str = "music",
        max_results: int = 10,
    ) -> dict:
        """多平台关键字搜索，结果去重 + 质量排序 + 已入库标记"""
        if not platforms:
            platforms = list(DEFAULT_PLATFORMS)

        # 过滤无效平台
        valid_platforms = [p for p in platforms if p in SEARCH_EXTRACTORS]
        if not valid_platforms:
            return {
                "results": [],
                "total_count": 0,
                "platforms_searched": [],
                "dedup_removed_count": 0,
            }

        loop = asyncio.get_running_loop()

        # 并行搜索所有平台
        with ThreadPoolExecutor(max_workers=len(valid_platforms)) as executor:
            futures = []
            for platform in valid_platforms:
                extractor = SEARCH_EXTRACTORS[platform]
                futures.append(
                    loop.run_in_executor(
                        executor,
                        self._search_single_platform,
                        extractor["prefix"],
                        keyword,
                        max_results,
                        platform,
                    )
                )
            platform_results = await asyncio.gather(*futures, return_exceptions=True)

        # 合并结果
        all_results = []
        searched_platforms = []
        for i, result in enumerate(platform_results):
            platform_name = valid_platforms[i]
            if isinstance(result, Exception):
                logger.warning(f"平台 {platform_name} 搜索失败: {result}")
                continue
            searched_platforms.append(platform_name)
            all_results.extend(result)

        # 计算质量分数（含关键词相关性，此处无 artist_name）
        for item in all_results:
            item["quality_score"] = self._calculate_quality_score(item, content_type, keyword)

        # 过滤完全不相关结果（score=0 表示关键词在标题中无任何匹配）
        if keyword:
            before = len(all_results)
            all_results = [r for r in all_results if r["quality_score"] > 0]
            filtered = before - len(all_results)
            if filtered:
                logger.info(f"相关性过滤：移除 {filtered} 条不相关结果")

        # 去重
        deduped, removed_count = self._deduplicate_results(all_results)

        # 按质量分数排序
        deduped.sort(key=lambda x: x["quality_score"], reverse=True)

        # 标记已入库
        await self._check_db_exists(deduped)

        return {
            "results": deduped,
            "total_count": len(deduped),
            "platforms_searched": searched_platforms,
            "dedup_removed_count": removed_count,
        }

    def _search_single_platform(
        self,
        prefix: str,
        keyword: str,
        max_results: int,
        platform: str,
    ) -> List[dict]:
        """单平台搜索（同步，在线程池中执行）"""
        import yt_dlp

        search_query = f"{prefix}{max_results}:{keyword}"
        ydl_opts = {
            **self._base_ydl_opts(),
            "extract_flat": True,
            "skip_download": True,
        }

        results = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if not info:
                return []

            entries = info.get("entries", [])
            if not entries:
                # 单结果
                entries = [info] if info.get("title") else []

            for entry in entries:
                if entry is None:
                    continue
                results.append({
                    "platform": platform,
                    "url": entry.get("url") or entry.get("webpage_url") or "",
                    "title": entry.get("title") or "",
                    "duration": entry.get("duration") or 0,
                    "view_count": entry.get("view_count") or 0,
                    "like_count": entry.get("like_count") or 0,
                    "thumbnail": entry.get("thumbnail") or (
                        entry.get("thumbnails", [{}])[0].get("url", "") if entry.get("thumbnails") else ""
                    ),
                    "uploader": entry.get("uploader") or entry.get("channel") or "",
                    "upload_date": entry.get("upload_date") or "",
                })

        return results

    def _calculate_quality_score(
        self, entry: dict, content_type: str, keyword: str = "", artist_name: str = ""
    ) -> float:
        """计算质量评分 (0-100)

        当提供 keyword 时，相关性作为首要维度，
        且相关性为 0（标题与关键词无任何匹配）时直接返回 0，确保不相关结果被过滤。
        当同时提供 artist_name 时，uploader 匹配额外加分。
        最终加上平台固定加成（PLATFORM_BONUS），实际得分范围约 0-108。
        """
        score = 0.0
        has_kw = bool(keyword.strip())
        has_artist = bool(artist_name.strip())

        # 动态权重表
        if has_kw and has_artist:
            w = dict(relevance=30, artist=20, view=20, like=12, dur=10, fresh=8)
        elif has_kw:
            w = dict(relevance=40, artist=0, view=25, like=15, dur=12, fresh=8)
        else:
            w = dict(relevance=0, artist=0, view=35, like=25, dur=20, fresh=20)

        # 相关性 — 关键词与标题匹配度
        if has_kw:
            relevance = self._calculate_title_relevance(entry.get("title", ""), keyword)
            if relevance == 0.0:
                return 0.0  # 完全不相关，直接排除
            score += relevance * w["relevance"]

        # 艺术家匹配（仅加分，不惩罚）
        if has_artist:
            artist_score = self._calculate_artist_match(entry.get("uploader", ""), artist_name)
            score += artist_score * w["artist"]

        w_view = w["view"]
        w_like = w["like"]
        w_dur  = w["dur"]
        w_fresh = w["fresh"]

        # 播放量 — log10 归一化，10万=满分
        view_count = entry.get("view_count") or 0
        if view_count > 0:
            view_score = min(math.log10(view_count + 1) / 5.0, 1.0)
            score += view_score * w_view

        # 点赞数 — log10 归一化，1万=满分
        like_count = entry.get("like_count") or 0
        if like_count > 0:
            like_score = min(math.log10(like_count + 1) / 4.0, 1.0)
            score += like_score * w_like

        # 时长匹配
        duration = entry.get("duration") or 0
        if duration > 0:
            pref_min, pref_max = DURATION_PREFERENCES.get(content_type, (120, 480))
            if pref_min <= duration <= pref_max:
                dur_score = 1.0
            elif duration < pref_min:
                dur_score = max(0, duration / pref_min)
            else:
                dur_score = max(0, 1.0 - (duration - pref_max) / pref_max)
            score += dur_score * w_dur

        # 时效性 — 越新越高
        upload_date = entry.get("upload_date") or ""
        if upload_date and len(upload_date) == 8:
            try:
                dt = datetime.strptime(upload_date, "%Y%m%d")
                days_ago = (datetime.now() - dt).days
                freshness = max(0, 1.0 - days_ago / 1825)  # 5年衰减
                score += freshness * w_fresh
            except ValueError:
                pass

        score += PLATFORM_BONUS.get(entry.get("platform", ""), 0)
        return round(score, 1)

    @staticmethod
    def _calculate_title_relevance(title: str, keyword: str) -> float:
        """计算标题与搜索关键词的相关性 (0.0 - 1.0)

        逐词检查关键词各分词是否出现在标题中，返回匹配比例。
        """
        title_lower = title.strip().lower()
        keyword_lower = keyword.strip().lower()

        if not title_lower or not keyword_lower:
            return 0.0

        # 完整关键词直接命中
        if keyword_lower in title_lower:
            return 1.0

        # 分词逐一匹配
        terms = [t for t in keyword_lower.split() if t]
        if not terms:
            return 0.0

        matched = sum(1 for term in terms if term in title_lower)
        return matched / len(terms)

    @staticmethod
    def _calculate_artist_match(uploader: str, artist_name: str) -> float:
        """检查 uploader 是否匹配艺术家名 (0.0 或 1.0)

        先直接 substring 匹配，再用拼音兜底（针对中文艺术家名 + 英文 uploader 的情况）。
        只加分，不惩罚（未匹配返回 0.0，不影响总分）。
        """
        if not uploader or not artist_name:
            return 0.0
        uploader_lower = uploader.lower()
        if artist_name.lower() in uploader_lower:
            return 1.0
        # 拼音兜底：如 "周杰伦" → "zhoujielun"，可命中上传者名为拼音的情况（如 "zhoujielun_music"）
        try:
            pinyin = "".join(lazy_pinyin(artist_name)).lower()
            if pinyin and len(pinyin) >= 3 and pinyin in uploader_lower:
                return 1.0
        except Exception:
            pass
        return 0.0

    def _deduplicate_results(
        self, results: List[dict]
    ) -> Tuple[List[dict], int]:
        """标题去重，同标题保留 quality_score 最高的"""
        seen: Dict[str, dict] = {}
        for item in results:
            norm_title = self._normalize_title(item.get("title", ""))
            if not norm_title:
                continue
            existing = seen.get(norm_title)
            if not existing or item.get("quality_score", 0) > existing.get("quality_score", 0):
                seen[norm_title] = item

        deduped = list(seen.values())
        removed = len(results) - len(deduped)
        return deduped, removed

    @staticmethod
    def _normalize_title(title: str) -> str:
        """标题归一化：lowercase → 去标点 → 合并空格"""
        title = title.lower().strip()
        # 去除标点符号
        title = re.sub(r'[^\w\s]', '', title, flags=re.UNICODE)
        # 合并连续空格
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    async def _check_db_exists(self, results: List[dict]) -> None:
        """查询 DB 标记已入库内容"""
        if not results:
            return

        # 收集所有标题
        titles = {item.get("title", "") for item in results}
        titles.discard("")

        if not titles:
            for item in results:
                item["exists_in_db"] = False
            return

        # 并行查询所有标题
        async def _check_single(title: str) -> Optional[str]:
            try:
                result = await self.content_service.list_contents(
                    keyword=title, page=1, page_size=1
                )
                for content_item in result.get("items", []):
                    if content_item.get("title") == title:
                        return title
            except Exception:
                pass
            return None

        checks = await asyncio.gather(*[_check_single(t) for t in titles])
        existing_titles = {t for t in checks if t is not None}

        for item in results:
            item["exists_in_db"] = item.get("title", "") in existing_titles

    def start_batch_download(
        self,
        urls: List[str],
        content_type: str,
        category_id: int,
        artist_name: Optional[str] = None,
        artist_type: str = "singer",
        tag_ids: Optional[List[int]] = None,
        age_min: int = 0,
        age_max: int = 12,
    ) -> DownloadTask:
        """批量下载选中项"""
        if self.task_manager.active_count() >= MAX_CONCURRENT_DOWNLOADS:
            from ..models.response import BusinessException, ErrorCode
            raise BusinessException(
                ErrorCode.REQUEST_TOO_FREQUENT,
                f"已有 {MAX_CONCURRENT_DOWNLOADS} 个下载任务在执行，请等待完成后再试"
            )

        # 合并 URL 用逗号分隔作为任务标识
        combined_url = f"batch({len(urls)})"
        params = {
            "content_type": content_type,
            "category_id": category_id,
            "artist_name": artist_name,
            "artist_type": artist_type,
            "tag_ids": tag_ids,
            "age_min": age_min,
            "age_max": age_max,
            "batch_urls": urls,
        }
        task = self.task_manager.create(combined_url, params)

        async_task = asyncio.create_task(self._execute_batch_download(task, urls))
        self.task_manager.set_async_task(task.task_id, async_task)

        return task

    async def _execute_batch_download(self, task: DownloadTask, urls: List[str]):
        """批量下载流程：逐 URL 提取信息并下载"""
        try:
            task.status = TaskStatus.EXTRACTING_INFO

            # 提取所有 URL 的信息
            all_entries = []
            for url in urls:
                try:
                    entries = await self._extract_info(url)
                    all_entries.extend(entries)
                except Exception as e:
                    logger.warning(f"提取 URL 信息失败 {url}: {e}")
                    # 创建占位 entry 以便标记失败
                    all_entries.append({"_failed": True, "_url": url, "_error": str(e)})

            if not all_entries:
                task.status = TaskStatus.FAILED
                task.error = "未找到可下载的内容"
                return

            task.total_count = len(all_entries)
            task.tracks = [
                TrackProgress(
                    index=i,
                    title=e.get("title", e.get("_url", f"Track {i+1}")),
                )
                for i, e in enumerate(all_entries)
            ]

            # 解析/创建艺术家（使用第一个有效 entry）
            valid_entries = [e for e in all_entries if not e.get("_failed")]
            artist_id = None
            if valid_entries:
                artist_id = await self._resolve_artist(
                    valid_entries[0],
                    task.params.get("artist_name"),
                    task.params.get("artist_type", "singer"),
                )

            # 逐个处理
            task.status = TaskStatus.DOWNLOADING
            for i, entry in enumerate(all_entries):
                if task.status == TaskStatus.CANCELLED:
                    break

                # 跳过提取失败的
                if entry.get("_failed"):
                    task.tracks[i].status = "failed"
                    task.tracks[i].error = entry.get("_error", "提取信息失败")[:200]
                    task.failed_count += 1
                    continue

                try:
                    content_id = await self._process_single_track(
                        entry=entry,
                        task=task,
                        track_index=i,
                        artist_id=artist_id,
                    )
                    task.tracks[i].status = "completed"
                    task.tracks[i].content_id = content_id
                    task.completed_count += 1
                except Exception as e:
                    logger.error(f"批量下载第 {i+1} 首失败: {e}", exc_info=True)
                    task.tracks[i].status = "failed"
                    task.tracks[i].error = str(e)[:200]
                    task.failed_count += 1

            # 最终状态
            if task.status == TaskStatus.CANCELLED:
                return
            if task.completed_count == 0:
                task.status = TaskStatus.FAILED
                task.error = "所有曲目均下载失败"
            else:
                task.status = TaskStatus.COMPLETED

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
        except Exception as e:
            logger.error(f"批量下载任务失败: {e}", exc_info=True)
            task.status = TaskStatus.FAILED
            task.error = str(e)[:300]

    async def _translate_to_english_query(
        self,
        artist_name: str,
        music_name: str,
        llm_service: Any,
    ) -> Optional[str]:
        """LLM 将中文歌手+曲名翻译为英文搜索词（Redis 缓存 30 天）"""
        if not artist_name or not music_name:
            return None
        cache_key = f"translate:v1:{artist_name.lower()}:{music_name.lower()}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.debug(f"翻译缓存命中: '{cached}'")
                    return cached
            except Exception:
                pass

        message = (
            f'歌手"{artist_name}"的歌曲"{music_name}"，'
            f'给出适合在 YouTube/SoundCloud 搜索的英文关键词，'
            f'只返回关键词，不超过5个词。'
        )
        try:
            result = await asyncio.wait_for(
                llm_service.chat_with_details(
                    message=message,
                    system_message="Only return English keywords for music search. No explanation.",
                    temperature=0.1,
                    max_tokens=20,
                    use_cache=True,
                ),
                timeout=3.0,
            )
            translated = result.response.strip()
            if translated and len(translated) < 100:
                if self.redis:
                    try:
                        await self.redis.set(cache_key, translated, ttl=TRANSLATION_CACHE_TTL)
                    except Exception:
                        pass
                logger.info(f"翻译英文query: '{artist_name} {music_name}' → '{translated}'")
                return translated
        except Exception as e:
            logger.debug(f"翻译query失败（已忽略）: {e}")
        return None

    async def _validate_with_llm(
        self,
        candidates: List[dict],
        artist_name: str,
        music_name: str,
        llm_service: Any,
    ) -> Optional[dict]:
        """用 LLM 从候选列表中挑选最匹配的结果

        仅在 artist_name 和 music_name 均存在时调用。
        返回选中的候选 dict，失败时返回 None（调用方回退到分数最高项）。
        """
        if not candidates or not llm_service:
            return None
        top = candidates[:3]
        items_text = "\n".join(
            f"{i + 1}. 标题：{c['title']}，上传者：{c.get('uploader', '未知')}"
            for i, c in enumerate(top)
        )
        message = (
            f"用户想听歌手"{artist_name}"的歌曲"{music_name}"。\n"
            f"以下是搜索结果候选：\n{items_text}\n\n"
            f"请返回最匹配的编号（1-{len(top)}），如果都不匹配则返回0。只返回数字。"
        )
        try:
            result = await llm_service.chat_with_details(
                message=message,
                system_message="你是音乐识别专家。根据歌手和曲名判断哪个搜索结果最匹配，只回复数字。",
                temperature=0.1,
                max_tokens=10,
                use_cache=False,
            )
            match = re.search(r'\d+', result.response)
            if match:
                idx = int(match.group())
                if 1 <= idx <= len(top):
                    logger.info(f"LLM验证选中: #{idx} '{top[idx - 1]['title']}'")
                    return top[idx - 1]
        except Exception as e:
            logger.warning(f"LLM验证失败，使用分数最高结果: {e}")
        return None

    async def search_and_download(
        self,
        keyword: str,
        content_type: str,
        category_id: int,
        platforms: Optional[List[str]] = None,
        timeout: float = 120.0,
        artist_name: Optional[str] = None,
        music_name: Optional[str] = None,
        artist_type: str = "singer",
        llm_service: Optional[Any] = None,
    ) -> Optional[int]:
        """搜索网上资源并下载，返回 content_id 或 None

        流程：双 query 并行搜索 → 合并去重 → LLM 验证（可选）→ 下载 → 等待完成 → 返回 content_id
        """
        # 输入清洗
        keyword = keyword.strip()[:100]
        if not keyword:
            return None

        # Redis 缓存检查（命中则跳过搜索+下载全流程）
        # cache_key 以 keyword（= "歌手 曲名" 或仅 "曲名"）为键；artist_name 已包含在 keyword 中，不重复添加
        cache_key = f"download:v1:{content_type}:{keyword}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.info(f"下载缓存命中: keyword='{keyword}', content_id={cached}")
                    return int(cached)
            except Exception:
                pass

        # 1. 构建搜索 query 列表（当曲名单独存在且与 keyword 不同时追加副 query）
        queries = [keyword]
        music_name_stripped = (music_name or "").strip()
        if music_name_stripped and music_name_stripped != keyword:
            queries.append(music_name_stripped)

        # 英文翻译 query（有歌手+曲名时，串行等待，上限 3s）
        # 设计选择：串行等待翻译结果后再并发搜索，确保英文 query 能加入同一批搜索；
        # "不阻塞" 指 LLM 失败/超时时静默跳过，主流程不受影响。
        if artist_name and music_name_stripped and llm_service:
            translated = await self._translate_to_english_query(
                artist_name, music_name_stripped, llm_service
            )
            if translated and translated.lower() not in {q.lower() for q in queries}:
                queries.append(translated)
                logger.info(f"追加英文翻译query: '{translated}'")

        # 2. 并行搜索所有 queries
        try:
            search_tasks = [
                self.search(q, platforms, content_type, max_results=5)
                for q in queries
            ]
            results_list = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"搜索超时: keyword='{keyword}'")
            return None
        except Exception as e:
            logger.error(f"搜索失败: keyword='{keyword}', error={e}")
            return None

        # 3. 合并去重：用主 keyword + artist_name 统一重新评分，同归一化标题保留分数高的
        merged: Dict[str, dict] = {}
        for result in results_list:
            if isinstance(result, Exception):
                logger.warning(f"某次搜索失败（已忽略）: {result}")
                continue
            for item in result.get("results", []):
                item["quality_score"] = self._calculate_quality_score(
                    item, content_type, keyword, artist_name or ""
                )
                key = self._normalize_title(item.get("title", ""))
                if key and (key not in merged or item["quality_score"] > merged[key]["quality_score"]):
                    merged[key] = item

        if not merged:
            logger.info(f"搜索无结果: keyword='{keyword}'")
            return None

        # 标记已入库
        candidates_list = sorted(merged.values(), key=lambda x: x["quality_score"], reverse=True)
        await self._check_db_exists(candidates_list)

        # 过滤 score==0 的结果（双 query 合并后仍无关）
        candidates_list = [c for c in candidates_list if c["quality_score"] > 0]
        if not candidates_list:
            logger.info(f"所有合并结果均不相关: keyword='{keyword}'")
            return None

        logger.info(
            f"双query合并后共 {len(candidates_list)} 个候选 "
            f"(queries={queries})"
        )

        # 4. 选最佳结果：优先未入库
        undownloaded = [c for c in candidates_list if not c.get("exists_in_db", False)]

        # LLM 从待下载候选（未入库）中验证最匹配项；已入库内容走下方 fallback 路径
        if undownloaded and llm_service and artist_name and music_name_stripped:
            validated = await self._validate_with_llm(
                undownloaded, artist_name, music_name_stripped, llm_service
            )
            best = validated or undownloaded[0]
        elif undownloaded:
            best = undownloaded[0]
        else:
            best = None

        if not best:
            # 全部已入库 — 尝试查找已有内容的 ID
            logger.info(f"搜索结果全部已入库: keyword='{keyword}'")
            for item in candidates_list:
                title = item.get("title", "")
                if not title:
                    continue
                try:
                    existing = await self.content_service.list_contents(
                        keyword=title, page=1, page_size=1
                    )
                    for c in existing.get("items", []):
                        if c.get("title") == title and c.get("id"):
                            logger.info(f"找到已入库内容: id={c['id']}, title='{title}'")
                            return c["id"]
                except Exception:
                    pass
            return None

        download_url = best.get("url")
        if not download_url:
            logger.warning(f"搜索结果无 URL: {best.get('title')}")
            return None

        logger.info(
            f"选中下载: title='{best.get('title')}', "
            f"score={best.get('quality_score')}, platform={best.get('platform')}, "
            f"url={download_url}"
        )

        # 5. 启动下载任务
        try:
            task = self.start_download(
                url=download_url,
                content_type=content_type,
                category_id=category_id,
                artist_name=artist_name or best.get("uploader"),
                artist_type=artist_type,
            )
        except Exception as e:
            logger.error(f"启动下载失败: {e}")
            return None

        # 6. 等待下载完成
        async_task = self.task_manager.get_async_task(task.task_id)
        if not async_task:
            logger.error(f"未找到异步任务: task_id={task.task_id}")
            return None

        try:
            await asyncio.wait_for(async_task, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"下载超时({timeout}s): task_id={task.task_id}")
            self.task_manager.cancel(task.task_id)
            return None
        except asyncio.CancelledError:
            logger.warning(f"下载被取消: task_id={task.task_id}")
            return None

        # 7. 检查结果
        if task.status != TaskStatus.COMPLETED:
            logger.warning(f"下载未成功: status={task.status}, error={task.error}")
            return None

        # 返回第一个成功的 content_id
        for track in task.tracks:
            if track.content_id:
                content_id = track.content_id
                logger.info(f"下载完成: content_id={content_id}, title='{track.title}'")
                if self.redis and content_id:
                    try:
                        await self.redis.set(cache_key, str(content_id), ttl=DOWNLOAD_CACHE_TTL)
                    except Exception:
                        pass
                return content_id

        logger.warning(f"下载完成但无 content_id: task_id={task.task_id}")
        return None

    @staticmethod
    def get_available_platforms() -> List[dict]:
        """返回可用搜索平台列表"""
        return [
            {"id": key, "label": val["label"]}
            for key, val in SEARCH_EXTRACTORS.items()
        ]
