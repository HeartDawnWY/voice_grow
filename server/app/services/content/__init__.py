"""
内容管理服务子模块

将 ContentService 按域拆分为 mixin 类
"""

from .base import ContentServiceBase
from .query import ContentQueryMixin
from .search import ContentSearchMixin
from .catalog import CatalogMixin
from .playback import PlaybackMixin
from .english import EnglishMixin
from .admin import AdminMixin

__all__ = [
    "ContentServiceBase",
    "ContentQueryMixin",
    "ContentSearchMixin",
    "CatalogMixin",
    "PlaybackMixin",
    "EnglishMixin",
    "AdminMixin",
]
