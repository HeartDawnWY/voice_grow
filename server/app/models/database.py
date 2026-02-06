"""
数据库模型定义

使用 SQLAlchemy 2.0 异步模式
基于详细设计文档 02_数据库设计.md
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List
from sqlalchemy import (
    String, Integer, BigInteger, Text, DateTime, Float, Boolean, ForeignKey,
    Index, JSON, UniqueConstraint
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """SQLAlchemy 基类"""
    pass


def ValueEnum(enum_class):
    """
    创建使用 enum value (而非 name) 存储的 SQLAlchemy Enum

    Python Enum:  MUSIC = "music"
    默认存储:     "MUSIC" (name)
    此函数存储:   "music" (value)
    """
    return SAEnum(
        enum_class,
        values_callable=lambda x: [e.value for e in x]
    )


class ContentType(PyEnum):
    """内容类型枚举"""
    STORY = "story"             # 故事
    MUSIC = "music"             # 音乐
    ENGLISH = "english"         # 英语
    SOUND = "sound"             # 音效


class ArtistType(PyEnum):
    """艺术家类型枚举"""
    SINGER = "singer"           # 歌手
    AUTHOR = "author"           # 作者
    NARRATOR = "narrator"       # 讲述者
    COMPOSER = "composer"       # 作曲家
    BAND = "band"               # 乐队


class ArtistRole(PyEnum):
    """艺术家角色枚举"""
    SINGER = "singer"           # 歌手
    AUTHOR = "author"           # 作者
    NARRATOR = "narrator"       # 讲述者
    COMPOSER = "composer"       # 作曲
    LYRICIST = "lyricist"       # 作词


class TagType(PyEnum):
    """标签类型枚举"""
    AGE = "age"                 # 年龄段
    SCENE = "scene"             # 场景
    MOOD = "mood"               # 情绪
    THEME = "theme"             # 主题
    FEATURE = "feature"         # 特色


class WordLevel(PyEnum):
    """单词难度级别"""
    BASIC = "basic"             # 基础
    INTERMEDIATE = "intermediate"  # 中级
    ADVANCED = "advanced"       # 高级


class PlayingState(PyEnum):
    """播放状态枚举"""
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    LOADING = "loading"


# ============================================
# 分类表 - 支持层级分类
# ============================================
class Category(Base):
    """
    分类表 - 支持多级分类树结构

    例如:
    故事 (level=1, path=/1/)
    ├── 童话故事 (level=2, path=/1/5/)
    │   ├── 格林童话 (level=3, path=/1/5/14/)
    │   └── 安徒生童话 (level=3, path=/1/5/15/)
    """
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )

    # 分类信息
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    name_pinyin: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 用于语音搜索
    type: Mapped[ContentType] = mapped_column(ValueEnum(ContentType), nullable=False)

    # 层级信息
    level: Mapped[int] = mapped_column(Integer, default=1)  # 层级深度
    path: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 分类路径 /1/5/14/

    # 显示信息
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    parent: Mapped[Optional["Category"]] = relationship(
        "Category", remote_side=[id], back_populates="children"
    )
    children: Mapped[List["Category"]] = relationship(
        "Category", back_populates="parent"
    )
    contents: Mapped[List["Content"]] = relationship(
        "Content", back_populates="category"
    )
    english_words: Mapped[List["EnglishWord"]] = relationship(
        "EnglishWord", back_populates="category"
    )

    __table_args__ = (
        Index("idx_category_parent", "parent_id"),
        Index("idx_category_type", "type"),
        Index("idx_category_type_level", "type", "level"),
        Index("idx_category_path", "path"),
        Index("idx_category_name_pinyin", "name_pinyin"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "name": self.name,
            "name_pinyin": self.name_pinyin,
            "type": self.type.value,
            "level": self.level,
            "path": self.path,
            "sort_order": self.sort_order,
            "icon": self.icon,
            "is_active": self.is_active,
        }


# ============================================
# 艺术家表 - 歌手、作者、讲述者
# ============================================
class Artist(Base):
    """
    艺术家表 - 歌手、作者、讲述者等

    支持别名搜索，如：周杰伦|Jay|杰伦|周董
    """
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 艺术家信息
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_pinyin: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    aliases: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 别名，用|分隔
    type: Mapped[ArtistType] = mapped_column(ValueEnum(ArtistType), nullable=False)

    # 媒体信息
    avatar_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    content_artists: Mapped[List["ContentArtist"]] = relationship(
        "ContentArtist", back_populates="artist"
    )

    __table_args__ = (
        Index("idx_artist_name", "name"),
        Index("idx_artist_name_pinyin", "name_pinyin"),
        Index("idx_artist_type", "type"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "name_pinyin": self.name_pinyin,
            "aliases": self.aliases.split("|") if self.aliases else [],
            "type": self.type.value,
            "avatar_path": self.avatar_path,
            "description": self.description,
            "is_active": self.is_active,
        }


# ============================================
# 标签表 - 灵活的标签系统
# ============================================
class Tag(Base):
    """
    标签表 - 按类型分组的标签

    类型包括：
    - age: 年龄段（胎教、0-3岁、3-6岁）
    - scene: 场景（睡前、早教、车载）
    - mood: 情绪（欢快、舒缓、温馨）
    - theme: 主题（经典、国学、科普）
    - feature: 特色（热门、精选、新上架）
    """
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 标签信息
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name_pinyin: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    type: Mapped[TagType] = mapped_column(ValueEnum(TagType), nullable=False)

    # 显示信息
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # UI颜色

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # 关系
    content_tags: Mapped[List["ContentTag"]] = relationship(
        "ContentTag", back_populates="tag"
    )

    __table_args__ = (
        Index("idx_tag_type", "type"),
        Index("idx_tag_name_pinyin", "name_pinyin"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "name_pinyin": self.name_pinyin,
            "type": self.type.value,
            "sort_order": self.sort_order,
            "color": self.color,
            "is_active": self.is_active,
        }


# ============================================
# 内容表 - 音频内容主表
# ============================================
class Content(Base):
    """
    内容表 - 存储故事、音乐、英语等内容元数据

    实际音频文件存储在 MinIO
    """
    __tablename__ = "contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 内容信息
    type: Mapped[ContentType] = mapped_column(ValueEnum(ContentType), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    title_pinyin: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 拼音搜索
    subtitle: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 存储路径 (MinIO)
    minio_path: Mapped[str] = mapped_column(String(500), nullable=False)
    cover_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # 音频信息
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 时长 (秒)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 文件大小 (字节)
    format: Mapped[str] = mapped_column(String(20), default="mp3")
    bitrate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 比特率

    # 适用范围
    age_min: Mapped[int] = mapped_column(Integer, default=0)
    age_max: Mapped[int] = mapped_column(Integer, default=12)

    # 统计
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    category: Mapped["Category"] = relationship("Category", back_populates="contents")
    content_artists: Mapped[List["ContentArtist"]] = relationship(
        "ContentArtist", back_populates="content", cascade="all, delete-orphan"
    )
    content_tags: Mapped[List["ContentTag"]] = relationship(
        "ContentTag", back_populates="content", cascade="all, delete-orphan"
    )
    play_history: Mapped[List["PlayHistory"]] = relationship(
        "PlayHistory", back_populates="content"
    )

    __table_args__ = (
        Index("idx_content_type_category", "type", "category_id"),
        Index("idx_content_title", "title"),
        Index("idx_content_title_pinyin", "title_pinyin"),
        Index("idx_content_play_count", "play_count"),
        Index("idx_content_created_at", "created_at"),
        Index("idx_content_active_type", "is_active", "type"),
        Index("idx_content_active_type_playcount", "is_active", "type", "play_count"),
    )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type.value,
            "category_id": self.category_id,
            "category_name": self.category.name if self.category else None,
            "title": self.title,
            "title_pinyin": self.title_pinyin,
            "subtitle": self.subtitle,
            "description": self.description,
            "minio_path": self.minio_path,
            "cover_path": self.cover_path,
            "duration": self.duration,
            "file_size": self.file_size,
            "format": self.format,
            "age_min": self.age_min,
            "age_max": self.age_max,
            "play_count": self.play_count,
            "like_count": self.like_count,
            "is_active": self.is_active,
            "is_vip": self.is_vip,
            "artists": [ca.artist.to_dict() for ca in self.content_artists] if self.content_artists else [],
            "tags": [ct.tag.to_dict() for ct in self.content_tags] if self.content_tags else [],
        }


# ============================================
# 内容-艺术家关联表
# ============================================
class ContentArtist(Base):
    """
    内容-艺术家关联表 - 多对多关系

    支持指定角色（歌手、作者、讲述者等）和主要艺术家标记
    """
    __tablename__ = "content_artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False
    )
    artist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artists.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ArtistRole] = mapped_column(ValueEnum(ArtistRole), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否主要艺术家
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # 关系
    content: Mapped["Content"] = relationship("Content", back_populates="content_artists")
    artist: Mapped["Artist"] = relationship("Artist", back_populates="content_artists")

    __table_args__ = (
        UniqueConstraint("content_id", "artist_id", "role", name="uk_content_artist_role"),
        Index("idx_content_artist_content", "content_id"),
        Index("idx_content_artist_artist", "artist_id"),
        Index("idx_content_artist_artist_role", "artist_id", "role"),
        Index("idx_content_artist_primary", "artist_id", "is_primary", "content_id"),
    )


# ============================================
# 内容-标签关联表
# ============================================
class ContentTag(Base):
    """
    内容-标签关联表 - 多对多关系
    """
    __tablename__ = "content_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # 关系
    content: Mapped["Content"] = relationship("Content", back_populates="content_tags")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="content_tags")

    __table_args__ = (
        UniqueConstraint("content_id", "tag_id", name="uk_content_tag"),
        Index("idx_content_tag_content", "content_id"),
        Index("idx_content_tag_tag", "tag_id"),
    )


# ============================================
# 英语单词表
# ============================================
class EnglishWord(Base):
    """
    英语单词表 - 英语学习功能
    """
    __tablename__ = "english_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 单词信息
    word: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    phonetic_us: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 美式音标
    phonetic_uk: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 英式音标
    translation: Mapped[str] = mapped_column(String(500), nullable=False)

    # 音频路径
    audio_us_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    audio_uk_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # 分类
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    level: Mapped[WordLevel] = mapped_column(ValueEnum(WordLevel), default=WordLevel.BASIC)

    # 例句
    example_sentence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    example_translation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    example_audio_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # 扩展
    synonyms: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    antonyms: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    word_forms: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    category: Mapped[Optional["Category"]] = relationship(
        "Category", back_populates="english_words"
    )

    __table_args__ = (
        Index("idx_word_category", "category_id"),
        Index("idx_word_level", "level"),
        Index("idx_word_category_level", "category_id", "level"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "word": self.word,
            "phonetic_us": self.phonetic_us,
            "phonetic_uk": self.phonetic_uk,
            "translation": self.translation,
            "audio_us_path": self.audio_us_path,
            "audio_uk_path": self.audio_uk_path,
            "category_id": self.category_id,
            "category_name": self.category.name if self.category else None,
            "level": self.level.value,
            "example_sentence": self.example_sentence,
            "example_translation": self.example_translation,
        }


# ============================================
# 播放历史表
# ============================================
class PlayHistory(Base):
    """
    播放历史表 - 记录用户播放记录
    """
    __tablename__ = "play_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 关联
    device_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False
    )
    content_type: Mapped[ContentType] = mapped_column(ValueEnum(ContentType), nullable=False)

    # 播放信息
    played_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    duration_played: Mapped[int] = mapped_column(Integer, default=0)  # 已播放时长 (秒)
    play_position: Mapped[int] = mapped_column(Integer, default=0)  # 播放位置 (秒)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    play_source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # search/recommend/history/command

    # 关系
    content: Mapped["Content"] = relationship("Content", back_populates="play_history")

    __table_args__ = (
        Index("idx_history_device_time", "device_id", "played_at"),
        Index("idx_history_content", "content_id"),
        Index("idx_history_device_content", "device_id", "content_id"),
        Index("idx_history_played_at", "played_at"),
    )


# ============================================
# 设备会话表
# ============================================
class DeviceSession(Base):
    """
    设备会话表 - 记录设备连接状态和会话信息
    """
    __tablename__ = "device_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 设备信息
    device_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    device_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    device_sn: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    device_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # 会话状态
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_disconnected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 播放状态
    current_content_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("contents.id", ondelete="SET NULL"), nullable=True
    )
    playing_state: Mapped[PlayingState] = mapped_column(
        ValueEnum(PlayingState), default=PlayingState.IDLE
    )
    play_position: Mapped[int] = mapped_column(Integer, default=0)
    volume: Mapped[int] = mapped_column(Integer, default=50)

    # 会话数据 (JSON)
    session_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    current_content: Mapped[Optional["Content"]] = relationship("Content", lazy="joined")

    __table_args__ = (
        Index("idx_session_connected", "is_connected"),
    )
