"""
删除内容处理器

支持语音删除内容，包含多轮对话确认流程：
1. 用户说"删除xxx" → 搜索 → 询问确认
2. 用户确认/取消 → 执行软删除或取消
"""

import logging
from typing import Optional, Dict, List, Any

from ..core.nlu import NLUResult
from ..core.tts import TTSService
from ..services.content_service import ContentService
from .base import BaseHandler, HandlerResponse

logger = logging.getLogger(__name__)

# 确认关键词（多字优先，短词用精确匹配避免子串误判）
CONFIRM_PHRASES = {"是的", "确认", "好的", "可以", "没问题", "删除", "删吧", "嗯嗯"}
CONFIRM_EXACT = {"是", "对", "好", "嗯", "行"}
# 取消关键词（否定词优先检测，防止 "不是"→"是" 误判为确认）
CANCEL_PHRASES = {"取消", "不要", "不用", "算了", "不删", "别删", "不是", "不好", "不对"}
CANCEL_EXACT = {"不", "否"}

# 语音删除安全上限
MAX_VOICE_DELETE = 10


class DeleteHandler(BaseHandler):
    """删除内容处理器"""

    def __init__(self, content_service: ContentService, tts_service: TTSService):
        super().__init__(content_service, tts_service)

    async def handle(
        self,
        nlu_result: NLUResult,
        device_id: str,
        context: Optional[Dict] = None
    ) -> HandlerResponse:
        """
        处理删除意图：搜索内容 → 询问确认

        slots:
            content_name: 要删除的内容名称
        """
        content_name = nlu_result.slots.get("content_name", "").strip()
        if not content_name:
            return HandlerResponse(text="请告诉我要删除什么内容")

        # 搜索匹配的内容
        results = await self.content_service.smart_search(content_name, limit=MAX_VOICE_DELETE + 1)
        if not results:
            return HandlerResponse(text=f"没有找到关于{content_name}的内容")

        # 安全上限：匹配过多时拒绝语音删除
        if len(results) > MAX_VOICE_DELETE:
            return HandlerResponse(
                text=f"找到了超过{MAX_VOICE_DELETE}条关于{content_name}的内容，数量太多，请在管理后台操作"
            )

        # 设置 pending_action（通过 context 回调）
        set_pending = context.get("set_pending_action") if context else None
        if set_pending:
            content_ids = [r["id"] for r in results]
            set_pending(
                action_type="delete_content",
                data={
                    "content_name": content_name,
                    "content_ids": content_ids,
                    "count": len(results),
                },
                handler_name="delete",
            )

        count = len(results)
        return HandlerResponse(
            text=f"找到了{count}条关于{content_name}的内容，是否要删除？",
            continue_listening=True,
        )

    async def handle_confirmation(
        self,
        text: str,
        pending_data: Dict[str, Any],
        device_id: str,
        context: Optional[Dict] = None,
    ) -> HandlerResponse:
        """
        处理用户对删除操作的确认或取消

        Args:
            text: 用户回复文本
            pending_data: pending_action 中存储的数据
            device_id: 设备 ID
            context: 上下文
        """
        text_stripped = text.strip()
        content_name = pending_data.get("content_name", "")
        content_ids: List[int] = pending_data.get("content_ids", [])

        # 取消优先于确认（安全原则：删除操作宁可漏删不可误删）
        if self._is_cancel(text_stripped):
            return HandlerResponse(text="好的，已取消删除")
        elif self._is_confirm(text_stripped):
            return await self._execute_delete(content_ids, content_name)
        else:
            return HandlerResponse(text="没有听懂，已取消删除操作")

    def _is_confirm(self, text: str) -> bool:
        """检测确认意图（多字子串匹配 + 短词精确匹配）"""
        for phrase in CONFIRM_PHRASES:
            if phrase in text:
                return True
        return text in CONFIRM_EXACT

    def _is_cancel(self, text: str) -> bool:
        """检测取消意图（多字子串匹配 + 短词精确匹配）"""
        for phrase in CANCEL_PHRASES:
            if phrase in text:
                return True
        return text in CANCEL_EXACT

    async def _execute_delete(
        self, content_ids: List[int], content_name: str
    ) -> HandlerResponse:
        """执行批量软删除"""
        success_count = 0
        fail_count = 0

        for cid in content_ids:
            try:
                ok = await self.content_service.delete_content(cid, hard=False)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"删除内容失败: id={cid}, error={e}")
                fail_count += 1

        if fail_count == 0:
            return HandlerResponse(text=f"已成功删除{success_count}条内容")
        elif success_count == 0:
            return HandlerResponse(text=f"删除失败，请稍后再试")
        else:
            return HandlerResponse(
                text=f"已删除{success_count}条内容，{fail_count}条删除失败"
            )
