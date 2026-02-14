"""
YouTube 下载服务

从 YouTube 下载音频，转换为 M4A，上传至 MinIO 并创建 DB 记录
"""

import asyncio
import hashlib
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from pypinyin import lazy_pinyin

from ..models.database import ArtistType, ContentType
from .content_service import ContentService
from .minio_service import MinIOService

logger = logging.getLogger(__name__)

MAX_CONCURRENT_DOWNLOADS = 3


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


# ========== 核心服务 ==========

class YouTubeService:
    def __init__(self, minio_service: MinIOService, content_service: ContentService):
        self.minio = minio_service
        self.content_service = content_service
        self.task_manager = DownloadTaskManager()

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
            task.error = str(e)[:300]

    async def _extract_info(self, url: str) -> List[dict]:
        """提取 YouTube 视频/播放列表信息"""
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
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
        while True:
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
            description="Auto-created from YouTube",
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
                "quiet": True,
                "no_warnings": True,
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
