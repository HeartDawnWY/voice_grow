"""
NLU 自然语言理解服务

规则 + LLM 混合意图识别
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class Intent(Enum):
    """意图枚举"""
    # 故事相关
    PLAY_STORY = "play_story"                   # 播放故事
    PLAY_STORY_CATEGORY = "play_story_category"  # 按分类播放故事
    PLAY_STORY_BY_NAME = "play_story_by_name"    # 按名称播放故事

    # 音乐相关
    PLAY_MUSIC = "play_music"                   # 播放音乐
    PLAY_MUSIC_CATEGORY = "play_music_category"  # 按分类播放音乐
    PLAY_MUSIC_BY_NAME = "play_music_by_name"    # 按名称播放音乐
    PLAY_MUSIC_BY_ARTIST = "play_music_by_artist"  # 按艺术家播放音乐

    # 播放控制
    CONTROL_PAUSE = "control_pause"             # 暂停
    CONTROL_RESUME = "control_resume"           # 继续
    CONTROL_STOP = "control_stop"               # 停止
    CONTROL_NEXT = "control_next"               # 下一个
    CONTROL_PREVIOUS = "control_previous"       # 上一个
    CONTROL_VOLUME_UP = "control_volume_up"     # 音量增大
    CONTROL_VOLUME_DOWN = "control_volume_down" # 音量减小

    # 英语学习
    ENGLISH_LEARN = "english_learn"             # 学英语
    ENGLISH_WORD = "english_word"               # 查单词
    ENGLISH_FOLLOW = "english_follow"           # 跟读

    # 对话
    CHAT = "chat"                               # 闲聊

    # 播放模式
    CONTROL_PLAY_MODE = "control_play_mode"     # 播放模式切换

    # 内容管理
    DELETE_CONTENT = "delete_content"           # 删除内容

    # 系统
    SYSTEM_TIME = "system_time"                 # 查询时间
    SYSTEM_WEATHER = "system_weather"           # 查询天气

    # 未知
    UNKNOWN = "unknown"


@dataclass
class NLUResult:
    """NLU 识别结果"""
    intent: Intent
    slots: Dict[str, Any]
    confidence: float
    raw_text: str

    def __str__(self) -> str:
        return f"NLUResult(intent={self.intent.value}, slots={self.slots}, confidence={self.confidence:.2f})"


# 分类名称映射
CATEGORY_MAPPING = {
    # 故事分类
    '睡前': 'bedtime',
    '童话': 'fairy_tale',
    '寓言': 'fable',
    '科普': 'science',
    '成语': 'idiom',
    '历史': 'history',
    '神话': 'myth',

    # 音乐分类
    '儿歌': 'nursery_rhyme',
    '摇篮曲': 'lullaby',
    '胎教音乐': 'prenatal',
    '胎教': 'prenatal',
    '古典音乐': 'classical',
    '古典': 'classical',
    '流行': 'pop',
    '英文歌': 'english',
}


class NLUService:
    """
    意图识别服务

    使用规则匹配 + LLM 混合策略
    """

    def __init__(self, llm_service=None):
        """
        初始化 NLU 服务

        Args:
            llm_service: LLM 服务实例 (可选，用于复杂意图识别)
        """
        self.llm_service = llm_service
        self.rules = self._init_rules()

    def _init_rules(self) -> List[Tuple[str, Intent, Dict[str, int]]]:
        """
        初始化意图规则

        返回: [(正则表达式, 意图, 槽位映射)]
        槽位映射: {槽位名: 正则组索引}
        """
        return [
            # ========== 故事播放 ==========
            # 分类故事（精确关键词，regex 可靠）
            (r'(播放|来点?|讲)(睡前|童话|寓言|科普|成语|历史|神话)故事', Intent.PLAY_STORY_CATEGORY, {'category': 2}),
            # 通用: "讲个故事", "来点故事"（无名字提取，regex 可靠）
            (r'(讲|说|播放|来)(一?(个|首)|点)?故事$', Intent.PLAY_STORY, {}),
            # 含故事名的请求 → 不用 regex 提取名字，交给 LLM（跳过，走 LLM 兜底）

            # ========== 音乐播放 ==========
            # 分类音乐（精确关键词，regex 可靠）
            (r'(播放|放|来点?)(儿歌|摇篮曲|胎教音乐|胎教|古典音乐|古典|流行|英文歌)', Intent.PLAY_MUSIC_CATEGORY, {'category': 2}),
            # 通用: "播放音乐", "来首歌"（无名字提取，regex 可靠）
            (r'(播放|放|来)(一?首|点)?音乐$', Intent.PLAY_MUSIC, {}),
            (r'(播放|放|来)(一?首|点)?歌$', Intent.PLAY_MUSIC, {}),
            # 含歌名/歌手的请求 → 交给 LLM 提取 slots

            # ========== 播放控制 ==========
            (r'^(暂停|停一?下|停止播放)$', Intent.CONTROL_PAUSE, {}),
            (r'^(继续|继续播放)$', Intent.CONTROL_RESUME, {}),
            (r'^(停止|停|关闭|别放了)$', Intent.CONTROL_STOP, {}),
            (r'(下一个|下一首|切歌|换一个|换一首)', Intent.CONTROL_NEXT, {}),
            (r'(上一个|上一首)', Intent.CONTROL_PREVIOUS, {}),
            (r'(大声点|音量大一点|声音大一点|调大|大点声)', Intent.CONTROL_VOLUME_UP, {}),
            (r'(小声点|音量小一点|声音小一点|调小|小点声)', Intent.CONTROL_VOLUME_DOWN, {}),
            (r'(单曲循环|列表循环|随机播放|顺序播放)', Intent.CONTROL_PLAY_MODE, {'play_mode': 1}),

            # ========== 英语学习 ==========
            (r'(学英语|英语学习|学习英语|教我英语)', Intent.ENGLISH_LEARN, {}),
            (r'(.+)(用英语|英文)(怎么说|怎么读)', Intent.ENGLISH_WORD, {'word': 1}),
            (r'(英语|英文)怎么说(.+)', Intent.ENGLISH_WORD, {'word': 2}),
            (r'(跟我读|跟读)(.+)', Intent.ENGLISH_FOLLOW, {'word': 2}),
            (r'(.+)(英语|英文)怎么读', Intent.ENGLISH_WORD, {'word': 1}),

            # ========== 内容管理 ==========
            (r'(删除|删掉|移除)(.+)', Intent.DELETE_CONTENT, {'content_name': 2}),

            # ========== 系统查询 ==========
            (r'(现在)?几点(了|钟)?', Intent.SYSTEM_TIME, {}),
            (r'(什么)?时间', Intent.SYSTEM_TIME, {}),
            (r'(今天)?(周几|星期几)', Intent.SYSTEM_TIME, {}),
            (r'(今天|明天|后天)?.{0,2}(天气|气温|温度)', Intent.SYSTEM_WEATHER, {}),
            (r'(外面|今天)(冷|热|下雨|下雪)吗', Intent.SYSTEM_WEATHER, {}),
            (r'(要不要|需不需要)(带伞|穿外套)', Intent.SYSTEM_WEATHER, {}),
        ]

    async def recognize(self, text: str) -> NLUResult:
        """
        识别用户意图

        Args:
            text: 用户输入文本

        Returns:
            NLUResult 包含意图、槽位和置信度
        """
        text = text.strip()
        if not text:
            return NLUResult(
                intent=Intent.UNKNOWN,
                slots={},
                confidence=0.0,
                raw_text=text
            )

        logger.debug(f"NLU 识别输入: '{text}'")

        # 1. 规则匹配
        result = self._rule_match(text)
        if result and result.confidence >= 0.8:
            logger.info(f"NLU 规则匹配: {result}")
            return result

        # 2. LLM 分类 (如果可用且规则匹配置信度较低)
        if self.llm_service and (result is None or result.confidence < 0.8):
            llm_result = await self._llm_classify(text)
            if llm_result.confidence > (result.confidence if result else 0):
                logger.info(f"NLU LLM 分类: {llm_result}")
                return llm_result

        # 3. 返回规则匹配结果或默认为对话
        if result:
            logger.info(f"NLU 使用规则结果: {result}")
            return result

        # 4. 默认为对话意图
        default_result = NLUResult(
            intent=Intent.CHAT,
            slots={},
            confidence=0.5,
            raw_text=text
        )
        logger.info(f"NLU 默认对话: {default_result}")
        return default_result

    def _rule_match(self, text: str) -> Optional[NLUResult]:
        """规则匹配"""
        for pattern, intent, slot_mapping in self.rules:
            match = re.search(pattern, text)
            if match:
                slots = {}

                # 提取槽位
                for slot_name, group_idx in slot_mapping.items():
                    if isinstance(group_idx, int) and group_idx <= len(match.groups()):
                        value = match.group(group_idx)
                        if value:
                            slots[slot_name] = value.strip()

                # 分类映射
                if 'category' in slots:
                    slots['category'] = self._map_category(slots['category'])

                return NLUResult(
                    intent=intent,
                    slots=slots,
                    confidence=0.9,
                    raw_text=text
                )

        return None

    def _map_category(self, category_text: str) -> str:
        """映射分类名称到英文"""
        return CATEGORY_MAPPING.get(category_text, category_text)

    async def _llm_classify(self, text: str) -> NLUResult:
        """
        使用 LLM 进行意图分类

        Args:
            text: 用户输入

        Returns:
            NLUResult
        """
        if not self.llm_service:
            return NLUResult(
                intent=Intent.CHAT,
                slots={},
                confidence=0.5,
                raw_text=text
            )

        try:
            # 构建分类提示
            prompt = self._build_classification_prompt(text)
            result = await self.llm_service.chat_with_details(
                prompt, [],
                temperature=0.1,
                system_message="你是一个精确的意图分类和实体提取系统。只返回JSON，不要返回任何其他内容。",
                use_cache=False,
            )
            response = result.response

            # 解析 LLM 响应
            return self._parse_llm_response(response, text)

        except Exception as e:
            logger.error(f"LLM 分类失败: {e}")
            return NLUResult(
                intent=Intent.CHAT,
                slots={},
                confidence=0.5,
                raw_text=text
            )

    def _build_classification_prompt(self, text: str) -> str:
        """构建 LLM 分类提示"""
        return f"""你是一个意图分类器。分析用户输入，返回JSON格式结果。

用户输入: "{text}"

可选意图:
play_story - 播放故事
play_story_by_name - 按名称播放故事(提取story_name)
play_music - 播放音乐(无指定歌手/歌名)
play_music_by_artist - 按歌手播放(如"播放林俊杰的歌",提取artist_name)
play_music_by_name - 按歌名播放(如"播放《晴天》",提取music_name,可选artist_name)
play_music_category - 按分类播放(儿歌/摇篮曲/古典等,提取category)
control_pause - 暂停
control_resume - 继续
control_stop - 停止
control_next - 下一个
control_previous - 上一个
control_volume_up - 音量增大
control_volume_down - 音量减小
control_play_mode - 播放模式切换
english_learn - 学英语
english_word - 查单词(提取word)
english_follow - 跟读
delete_content - 删除内容(如"删除小星星",提取content_name)
system_time - 查时间
system_weather - 查天气
chat - 闲聊

请返回JSON，格式: {{"intent":"意图名","slots":{{"key":"value"}}}}
slots只包含提取到的实体，没有则为空对象。
示例:
输入"播放林俊杰的歌" → {{"intent":"play_music_by_artist","slots":{{"artist_name":"林俊杰"}}}}
输入"播放《晴天》" → {{"intent":"play_music_by_name","slots":{{"music_name":"晴天"}}}}
输入"放周杰伦的晴天" → {{"intent":"play_music_by_name","slots":{{"artist_name":"周杰伦","music_name":"晴天"}}}}
输入"来首歌" → {{"intent":"play_music","slots":{{}}}}
输入"播放为什么天是蓝色的故事" → {{"intent":"play_story_by_name","slots":{{"story_name":"为什么天是蓝色的"}}}}
输入"讲个三只小猪的故事" → {{"intent":"play_story_by_name","slots":{{"story_name":"三只小猪"}}}}
输入"删除小星星" → {{"intent":"delete_content","slots":{{"content_name":"小星星"}}}}

只返回JSON，不要其他内容。"""

    def _parse_llm_response(self, response: str, raw_text: str) -> NLUResult:
        """解析 LLM 响应（JSON 格式）"""
        import json

        intent_mapping = {
            'play_story': Intent.PLAY_STORY,
            'play_story_by_name': Intent.PLAY_STORY_BY_NAME,
            'play_music': Intent.PLAY_MUSIC,
            'play_music_by_artist': Intent.PLAY_MUSIC_BY_ARTIST,
            'play_music_by_name': Intent.PLAY_MUSIC_BY_NAME,
            'play_music_category': Intent.PLAY_MUSIC_CATEGORY,
            'control_pause': Intent.CONTROL_PAUSE,
            'control_resume': Intent.CONTROL_RESUME,
            'control_stop': Intent.CONTROL_STOP,
            'control_next': Intent.CONTROL_NEXT,
            'control_previous': Intent.CONTROL_PREVIOUS,
            'control_volume_up': Intent.CONTROL_VOLUME_UP,
            'control_volume_down': Intent.CONTROL_VOLUME_DOWN,
            'control_play_mode': Intent.CONTROL_PLAY_MODE,
            'english_learn': Intent.ENGLISH_LEARN,
            'english_word': Intent.ENGLISH_WORD,
            'english_follow': Intent.ENGLISH_FOLLOW,
            'delete_content': Intent.DELETE_CONTENT,
            'system_time': Intent.SYSTEM_TIME,
            'system_weather': Intent.SYSTEM_WEATHER,
            'chat': Intent.CHAT,
        }

        # 尝试解析 JSON
        slots = {}
        intent_str = 'chat'
        try:
            # 提取 JSON（LLM 可能返回 markdown 包裹的 JSON）
            text = response.strip()
            if '```' in text:
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
                text = text.strip()
            data = json.loads(text)
            intent_str = data.get('intent', 'chat').strip().lower()
            slots = data.get('slots', {})
            if not isinstance(slots, dict):
                slots = {}
        except (json.JSONDecodeError, KeyError, AttributeError):
            # JSON 解析失败，回退到纯文本意图匹配
            intent_str = response.strip().lower()
            logger.warning(f"LLM 响应非 JSON，回退纯文本: '{intent_str}'")

        intent = intent_mapping.get(intent_str, Intent.CHAT)

        return NLUResult(
            intent=intent,
            slots=slots,
            confidence=0.7 if intent != Intent.CHAT else 0.5,
            raw_text=raw_text
        )
