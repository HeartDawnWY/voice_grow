"""
内容管理服务

管理故事、音乐、英语等内容的检索和播放
支持：
- 按艺术家搜索
- 按标签搜索
- 按分类层级搜索
- 拼音模糊搜索
- 智能综合搜索
"""

from .content.base import ContentServiceBase
from .content.query import ContentQueryMixin
from .content.search import ContentSearchMixin
from .content.catalog import CatalogMixin
from .content.playback import PlaybackMixin
from .content.english import EnglishMixin
from .content.admin import AdminMixin


class ContentService(
    ContentQueryMixin,
    ContentSearchMixin,
    CatalogMixin,
    PlaybackMixin,
    EnglishMixin,
    AdminMixin,
    ContentServiceBase,
):
    """
    内容管理服务（Facade）

    负责内容检索、播放 URL 生成、播放历史记录等
    支持新的分类、艺术家、标签查询
    """
    pass
