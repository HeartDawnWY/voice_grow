"""
意图处理器包

处理各种用户意图，生成响应
"""

from .base import HandlerResponse, BaseHandler
from .registry import HandlerRouter
from .story import StoryHandler
from .music import MusicHandler
from .english import EnglishHandler
from .chat import ChatHandler
from .control import ControlHandler
from .system import SystemHandler
from .delete import DeleteHandler

__all__ = [
    "HandlerResponse",
    "BaseHandler",
    "HandlerRouter",
    "StoryHandler",
    "MusicHandler",
    "EnglishHandler",
    "ChatHandler",
    "ControlHandler",
    "SystemHandler",
    "DeleteHandler",
]
