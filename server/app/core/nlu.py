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
            (r'(讲|说|播放|来)(一?个|点)?故事', Intent.PLAY_STORY, {}),
            (r'(我要|我想)?(听|播放)(.+)的?故事', Intent.PLAY_STORY_BY_NAME, {'story_name': 3}),
            (r'(播放|来点?|讲)(睡前|童话|寓言|科普|成语|历史|神话)故事', Intent.PLAY_STORY_CATEGORY, {'category': 2}),
            (r'(给我|帮我|我想)讲(一?个)?(.+)故事', Intent.PLAY_STORY_BY_NAME, {'story_name': 3}),

            # ========== 音乐播放 ==========
            (r'(播放|放|来)(一?首|点)?音乐', Intent.PLAY_MUSIC, {}),
            (r'(播放|放|来)(一?首|点)?歌', Intent.PLAY_MUSIC, {}),
            (r'(播放|放|来点?)(儿歌|摇篮曲|胎教音乐|胎教|古典音乐|古典|流行|英文歌)', Intent.PLAY_MUSIC_CATEGORY, {'category': 2}),
            (r'(播放|放|来一?首)《(.+)》', Intent.PLAY_MUSIC_BY_NAME, {'music_name': 2}),
            (r'(播放|放|唱)(.+)这首歌', Intent.PLAY_MUSIC_BY_NAME, {'music_name': 2}),
            (r'(我要|我想)听(.+)', Intent.PLAY_MUSIC_BY_NAME, {'music_name': 2}),

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
            response = await self.llm_service.chat(prompt, [])

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
        intent_list = [
            "play_story - 播放故事(讲故事/来个故事)",
            "play_music - 播放音乐(放歌/来首歌)",
            "control_pause - 暂停播放",
            "control_resume - 继续播放",
            "control_stop - 停止播放",
            "control_next - 下一个/下一首",
            "control_previous - 上一个/上一首",
            "control_volume_up - 大声点/音量调大",
            "control_volume_down - 小声点/音量调小",
            "control_play_mode - 播放模式切换(单曲循环/列表循环/随机播放/顺序播放)",
            "english_learn - 学英语/英语学习",
            "english_word - 查单词/用英语怎么说",
            "english_follow - 跟读",
            "system_time - 查询时间/几点了/星期几",
            "system_weather - 查询天气/气温/温度",
            "chat - 闲聊对话",
        ]

        return f"""你是一个意图分类器。请分析以下用户输入，返回最匹配的意图。

用户输入: "{text}"

可选意图:
{chr(10).join(intent_list)}

请只返回意图名称（如 play_story），不要返回其他内容。"""

    def _parse_llm_response(self, response: str, raw_text: str) -> NLUResult:
        """解析 LLM 响应"""
        response = response.strip().lower()

        # 意图映射
        intent_mapping = {
            'play_story': Intent.PLAY_STORY,
            'play_music': Intent.PLAY_MUSIC,
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
            'system_time': Intent.SYSTEM_TIME,
            'system_weather': Intent.SYSTEM_WEATHER,
            'chat': Intent.CHAT,
        }

        intent = intent_mapping.get(response, Intent.CHAT)

        return NLUResult(
            intent=intent,
            slots={},
            confidence=0.7 if intent != Intent.CHAT else 0.5,
            raw_text=raw_text
        )
