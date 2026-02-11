"""
HTTP 路由子模块

按域拆分路由，消除重复的类型映射
"""

from ...models.database import ContentType, ArtistType, TagType
from ...models.response import ErrorCode, BusinessException


CONTENT_TYPE_MAP = {
    "story": ContentType.STORY,
    "music": ContentType.MUSIC,
    "english": ContentType.ENGLISH,
}

ARTIST_TYPE_MAP = {
    "narrator": ArtistType.NARRATOR,
    "singer": ArtistType.SINGER,
    "composer": ArtistType.COMPOSER,
    "author": ArtistType.AUTHOR,
    "band": ArtistType.BAND,
}

TAG_TYPE_MAP = {
    "theme": TagType.THEME,
    "mood": TagType.MOOD,
    "age": TagType.AGE,
    "scene": TagType.SCENE,
    "feature": TagType.FEATURE,
}


def parse_content_type(type_str: str | None, *, required: bool = False) -> ContentType | None:
    """解析内容类型字符串为枚举

    required=True: type_str 为空或无效均抛异常
    required=False: type_str 为空返回 None，无效则抛异常
    """
    if not type_str:
        if required:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Content type is required")
        return None
    ct = CONTENT_TYPE_MAP.get(type_str)
    if ct is None:
        raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid content type: {type_str}")
    return ct


def parse_artist_type(type_str: str | None, *, required: bool = False) -> ArtistType | None:
    """解析艺术家类型字符串为枚举

    required=True: type_str 为空或无效均抛异常
    required=False: type_str 为空返回 None，无效则抛异常
    """
    if not type_str:
        if required:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Artist type is required")
        return None
    at = ARTIST_TYPE_MAP.get(type_str)
    if at is None:
        raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid artist type: {type_str}")
    return at


def parse_tag_type(type_str: str | None, *, required: bool = False) -> TagType | None:
    """解析标签类型字符串为枚举

    required=True: type_str 为空或无效均抛异常
    required=False: type_str 为空返回 None，无效则抛异常
    """
    if not type_str:
        if required:
            raise BusinessException(ErrorCode.INVALID_PARAMS, "Tag type is required")
        return None
    tt = TAG_TYPE_MAP.get(type_str)
    if tt is None:
        raise BusinessException(ErrorCode.INVALID_PARAMS, f"Invalid tag type: {type_str}")
    return tt
