"""
系统功能处理器
"""

import logging
from datetime import datetime
from typing import Optional, Dict

from ..core.nlu import Intent, NLUResult
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)


class SystemHandler(BaseHandler):
    """系统功能处理器"""

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """处理系统功能意图"""
        intent = nlu_result.intent

        if intent == Intent.SYSTEM_TIME:
            return self._handle_time()

        if intent == Intent.SYSTEM_WEATHER:
            return self._handle_weather(nlu_result)

        return HandlerResponse(text="这个功能暂时不支持")

    def _handle_time(self) -> HandlerResponse:
        """处理时间查询"""
        now = datetime.now()
        time_str = now.strftime("%H点%M分")
        date_str = now.strftime("%m月%d日")
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_str = weekday[now.weekday()]

        return HandlerResponse(
            text=f"现在是{date_str} {weekday_str} {time_str}"
        )

    def _handle_weather(self, nlu_result: NLUResult) -> HandlerResponse:
        """处理天气查询 (占位实现)"""
        return HandlerResponse(
            text="抱歉，天气查询功能正在开发中，暂时无法为你查询天气"
        )
