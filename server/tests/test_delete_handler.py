"""
DeleteHandler 单元测试

覆盖场景:
1.  搜索命中 → 询问确认 + continue_listening + 设置 pending_action
2.  搜索无结果 → 提示未找到
3.  空 content_name → 提示需要内容名
4.  超过安全上限 → 拒绝语音删除
5.  确认删除 → 批量软删除成功
6.  取消删除 → 提示已取消
7.  无关回复 → 提示没听懂 + 取消
8.  "不是"/"不好" 等否定短语 → 取消优先于确认（安全关键）
9.  短词精确匹配 → "是" 单独确认、"不" 单独取消
10. 部分删除失败 → 报告成功/失败数量
11. 全部删除失败 → 提示失败
12. NLU 规则匹配 → 删除意图识别正确
13. NLU LLM 映射 → delete_content 映射存在
14. PendingAction 超时判定
15. Pipeline pending_action 拦截（process_text）
16. Pipeline pending_action 过期回退 NLU
17. Pipeline set_pending_action 回调注入
18. HandlerRouter 注册 + get_handler_by_name
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.nlu import Intent, NLUResult, NLUService
from app.handlers.delete import (
    DeleteHandler,
    CONFIRM_PHRASES,
    CONFIRM_EXACT,
    CANCEL_PHRASES,
    CANCEL_EXACT,
    MAX_VOICE_DELETE,
)
from app.api.websocket import PendingAction


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_content_service():
    svc = MagicMock()
    svc.smart_search = AsyncMock(return_value=[])
    svc.delete_content = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def mock_tts_service():
    svc = MagicMock()
    svc.synthesize_to_url = AsyncMock(return_value="https://tts.example.com/audio.mp3")
    return svc


@pytest.fixture
def handler(mock_content_service, mock_tts_service):
    return DeleteHandler(
        content_service=mock_content_service,
        tts_service=mock_tts_service,
    )


@pytest.fixture
def context():
    """提供 set_pending_action 回调的 context"""
    pending_store = {}

    def _set_pending(action_type, data, handler_name, timeout=30.0):
        pending_store["action_type"] = action_type
        pending_store["data"] = data
        pending_store["handler_name"] = handler_name
        pending_store["timeout"] = timeout

    return {
        "set_pending_action": _set_pending,
        "play_tts": AsyncMock(),
        "play_url": AsyncMock(),
        "_store": pending_store,  # 测试用，检查回调是否被调用
    }


def make_nlu(intent: Intent, slots: dict = None, raw_text: str = "") -> NLUResult:
    return NLUResult(intent=intent, slots=slots or {}, confidence=0.95, raw_text=raw_text)


def make_search_results(count: int) -> list:
    """生成模拟搜索结果"""
    return [{"id": i + 1, "title": f"内容{i + 1}"} for i in range(count)]


# ── 1. 搜索命中 → 询问确认 ──────────────────────────────


@pytest.mark.asyncio
async def test_handle_found_asks_confirmation(handler, mock_content_service, context):
    """搜索到内容 → 返回确认提问 + continue_listening + 设置 pending_action"""
    mock_content_service.smart_search.return_value = make_search_results(3)

    result = await handler.handle(
        make_nlu(Intent.DELETE_CONTENT, {"content_name": "小星星"}),
        "dev-1",
        context,
    )

    assert "3条" in result.text
    assert "小星星" in result.text
    assert "是否要删除" in result.text
    assert result.continue_listening is True
    assert result.play_url is None

    # 验证 pending_action 被设置
    store = context["_store"]
    assert store["action_type"] == "delete_content"
    assert store["data"]["content_ids"] == [1, 2, 3]
    assert store["data"]["content_name"] == "小星星"
    assert store["handler_name"] == "delete"


# ── 2. 搜索无结果 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_not_found(handler, mock_content_service):
    """搜索无结果 → 提示未找到，不设 pending_action"""
    mock_content_service.smart_search.return_value = []

    result = await handler.handle(
        make_nlu(Intent.DELETE_CONTENT, {"content_name": "不存在的歌"}),
        "dev-1",
    )

    assert "没有找到" in result.text
    assert "不存在的歌" in result.text
    assert result.continue_listening is False


# ── 3. 空 content_name ───────────────────────────────────


@pytest.mark.asyncio
async def test_handle_empty_name(handler):
    """空内容名 → 提示需要内容名"""
    result = await handler.handle(
        make_nlu(Intent.DELETE_CONTENT, {"content_name": ""}),
        "dev-1",
    )
    assert "请告诉我" in result.text

    result2 = await handler.handle(
        make_nlu(Intent.DELETE_CONTENT, {}),
        "dev-1",
    )
    assert "请告诉我" in result2.text


# ── 4. 超过安全上限 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_exceeds_max_limit(handler, mock_content_service):
    """搜索结果超过 MAX_VOICE_DELETE → 拒绝语音删除"""
    mock_content_service.smart_search.return_value = make_search_results(MAX_VOICE_DELETE + 1)

    result = await handler.handle(
        make_nlu(Intent.DELETE_CONTENT, {"content_name": "故事"}),
        "dev-1",
    )

    assert "数量太多" in result.text
    assert "管理后台" in result.text
    assert result.continue_listening is False


@pytest.mark.asyncio
async def test_handle_at_max_limit_allowed(handler, mock_content_service, context):
    """搜索结果恰好等于 MAX_VOICE_DELETE → 允许"""
    mock_content_service.smart_search.return_value = make_search_results(MAX_VOICE_DELETE)

    result = await handler.handle(
        make_nlu(Intent.DELETE_CONTENT, {"content_name": "歌曲"}),
        "dev-1",
        context,
    )

    assert "是否要删除" in result.text
    assert result.continue_listening is True


# ── 5. 确认删除 → 批量软删除成功 ─────────────────────────


@pytest.mark.asyncio
async def test_confirmation_confirm_deletes(handler, mock_content_service):
    """用户确认 → 执行批量软删除"""
    pending_data = {"content_name": "小星星", "content_ids": [1, 2, 3], "count": 3}

    result = await handler.handle_confirmation("是的", pending_data, "dev-1")

    assert "已成功删除3条" in result.text
    assert mock_content_service.delete_content.call_count == 3
    # 验证全部使用软删除
    for call in mock_content_service.delete_content.call_args_list:
        assert call.kwargs.get("hard", False) is False


# ── 6. 取消删除 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmation_cancel(handler):
    """用户取消 → 提示已取消，不执行删除"""
    pending_data = {"content_name": "小星星", "content_ids": [1, 2], "count": 2}

    for cancel_word in ["取消", "不要", "算了", "不删", "别删", "不用"]:
        result = await handler.handle_confirmation(cancel_word, pending_data, "dev-1")
        assert "已取消" in result.text


# ── 7. 无关回复 → 取消 ───────────────────────────────────


@pytest.mark.asyncio
async def test_confirmation_unknown_cancels(handler):
    """用户说无关内容 → 提示没听懂 + 取消"""
    pending_data = {"content_name": "小星星", "content_ids": [1], "count": 1}

    for text in ["今天天气怎么样", "播放音乐", "讲个故事", "你好啊"]:
        result = await handler.handle_confirmation(text, pending_data, "dev-1")
        assert "没有听懂" in result.text
        assert "取消" in result.text


# ── 8. 否定短语 → 取消优先（安全关键） ───────────────────


@pytest.mark.asyncio
async def test_negation_phrases_cancel_priority(handler):
    """否定短语必须判定为取消，不能误判为确认"""
    pending_data = {"content_name": "test", "content_ids": [1], "count": 1}

    # 这些短语包含确认子串（"是"、"好"、"对"）但实际是否定
    negation_phrases = ["不是", "不好", "不对", "不是吧", "不好意思"]
    for text in negation_phrases:
        result = await handler.handle_confirmation(text, pending_data, "dev-1")
        assert "删除" not in result.text or "取消" in result.text, \
            f"'{text}' 不应触发删除！got: {result.text}"


# ── 9. 短词精确匹配 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_match_short_words(handler):
    """短词 "是"/"不" 只在单独说时匹配"""
    pending_data = {"content_name": "test", "content_ids": [1], "count": 1}

    # 单独 "是" → 确认
    result = await handler.handle_confirmation("是", pending_data, "dev-1")
    assert "已成功删除" in result.text

    # 单独 "不" → 取消
    result = await handler.handle_confirmation("不", pending_data, "dev-1")
    assert "已取消" in result.text

    # "是不是" → 取消（"不是" 子串命中 CANCEL_PHRASES）
    result = await handler.handle_confirmation("是不是", pending_data, "dev-1")
    assert "取消" in result.text or "没有听懂" in result.text


# ── 10. 部分删除失败 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_delete_failure(handler, mock_content_service):
    """部分删除失败 → 报告成功和失败数量"""
    mock_content_service.delete_content.side_effect = [True, False, True]
    pending_data = {"content_name": "test", "content_ids": [1, 2, 3], "count": 3}

    result = await handler.handle_confirmation("确认", pending_data, "dev-1")

    assert "已删除2条" in result.text
    assert "1条删除失败" in result.text


# ── 11. 全部删除失败 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_all_delete_failure(handler, mock_content_service):
    """全部删除失败 → 提示失败"""
    mock_content_service.delete_content.side_effect = Exception("DB error")
    pending_data = {"content_name": "test", "content_ids": [1, 2], "count": 2}

    result = await handler.handle_confirmation("是的", pending_data, "dev-1")

    assert "删除失败" in result.text


# ── 12. NLU 规则匹配 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_nlu_rule_match_delete():
    """NLU 规则正确识别删除意图并提取 content_name"""
    nlu = NLUService()

    test_cases = [
        ("删除小星星", "小星星"),
        ("删掉三只小猪", "三只小猪"),
        ("移除摇篮曲", "摇篮曲"),
        ("删除 周杰伦的歌", "周杰伦的歌"),  # 带空格
    ]

    for text, expected_name in test_cases:
        result = await nlu.recognize(text)
        assert result.intent == Intent.DELETE_CONTENT, f"'{text}' → {result.intent}"
        assert result.slots.get("content_name") == expected_name.strip(), \
            f"'{text}' → slots={result.slots}"
        assert result.confidence >= 0.8


# ── 13. NLU LLM 映射 ─────────────────────────────────────


def test_nlu_intent_mapping_has_delete():
    """LLM 意图映射包含 delete_content"""
    nlu = NLUService()
    result = nlu._parse_llm_response(
        '{"intent":"delete_content","slots":{"content_name":"测试"}}',
        "删除测试"
    )
    assert result.intent == Intent.DELETE_CONTENT
    assert result.slots.get("content_name") == "测试"


# ── 14. PendingAction 超时判定 ────────────────────────────


def test_pending_action_not_expired():
    """刚创建的 PendingAction 未过期"""
    pa = PendingAction(
        action_type="delete_content",
        data={"content_ids": [1]},
        handler_name="delete",
        timeout=30.0,
    )
    assert not pa.is_expired()


def test_pending_action_expired():
    """超时后 PendingAction 已过期"""
    pa = PendingAction(
        action_type="delete_content",
        data={"content_ids": [1]},
        handler_name="delete",
        created_at=time.time() - 60,  # 60 秒前创建
        timeout=30.0,
    )
    assert pa.is_expired()


# ── 15. Pipeline pending_action 拦截（process_text）──────


@pytest.mark.asyncio
async def test_pipeline_intercepts_pending_action():
    """process_text 检测到未过期 pending_action → 路由到 handle_confirmation"""
    from app.core.pipeline import VoicePipeline

    mock_delete_handler = MagicMock()
    mock_delete_handler.handle_confirmation = AsyncMock(
        return_value=MagicMock(text="已成功删除1条内容", play_url=None,
                                skip_interrupt=False, commands=[], queue_active=None,
                                continue_listening=False)
    )

    mock_router = MagicMock()
    mock_router.get_handler_by_name.return_value = mock_delete_handler

    pipeline = VoicePipeline(
        asr_service=MagicMock(),
        nlu_service=MagicMock(),
        tts_service=MagicMock(),
        handler_router=mock_router,
    )
    pipeline.respond = AsyncMock()

    conn = MagicMock()
    conn.device_id = "test-dev"
    conn.pending_action = PendingAction(
        action_type="delete_content",
        data={"content_name": "小星星", "content_ids": [1]},
        handler_name="delete",
    )

    with patch("app.core.pipeline.logger"):
        await pipeline.process_text("是的", "test-dev", conn)

    # pending_action 被消费
    assert conn.pending_action is None
    # handle_confirmation 被调用
    mock_delete_handler.handle_confirmation.assert_called_once_with(
        "是的", {"content_name": "小星星", "content_ids": [1]}, "test-dev", context=None
    )
    # respond 被调用
    pipeline.respond.assert_called_once()
    # NLU 未被调用
    pipeline.nlu.recognize.assert_not_called()


# ── 16. Pipeline pending_action 过期回退 NLU ─────────────


@pytest.mark.asyncio
async def test_pipeline_expired_pending_falls_through():
    """过期的 pending_action → 被清除，走正常 NLU"""
    from app.core.pipeline import VoicePipeline

    mock_nlu = MagicMock()
    mock_nlu.recognize = AsyncMock(return_value=NLUResult(
        intent=Intent.CHAT, slots={}, confidence=0.5, raw_text="你好"
    ))

    mock_chat_handler = MagicMock()
    mock_chat_handler.handle = AsyncMock(
        return_value=MagicMock(text="你好呀", play_url=None,
                                skip_interrupt=False, commands=[], queue_active=None,
                                continue_listening=False)
    )

    mock_router = MagicMock()
    mock_router.route = AsyncMock(return_value=mock_chat_handler.handle.return_value)

    pipeline = VoicePipeline(
        asr_service=MagicMock(),
        nlu_service=mock_nlu,
        tts_service=MagicMock(),
        handler_router=mock_router,
    )
    pipeline.respond = AsyncMock()

    conn = MagicMock()
    conn.device_id = "test-dev"
    # 已过期的 pending_action
    conn.pending_action = PendingAction(
        action_type="delete_content",
        data={"content_ids": [1]},
        handler_name="delete",
        created_at=time.time() - 60,
        timeout=30.0,
    )

    with patch("app.core.pipeline.logger"):
        await pipeline.process_text("你好", "test-dev", conn)

    # pending_action 被清除
    assert conn.pending_action is None
    # NLU 正常调用
    mock_nlu.recognize.assert_called_once_with("你好")
    # router 正常路由
    mock_router.route.assert_called_once()


# ── 17. Pipeline set_pending_action 回调注入 ─────────────


@pytest.mark.asyncio
async def test_pipeline_injects_set_pending_action():
    """process_text 传递给 handler 的 context 包含 set_pending_action"""
    from app.core.pipeline import VoicePipeline

    mock_nlu = MagicMock()
    mock_nlu.recognize = AsyncMock(return_value=NLUResult(
        intent=Intent.DELETE_CONTENT,
        slots={"content_name": "小星星"},
        confidence=0.9,
        raw_text="删除小星星"
    ))

    captured_context = {}

    async def capture_route(nlu_result, device_id, context):
        captured_context.update(context)
        return MagicMock(text="找到了1条", play_url=None,
                          skip_interrupt=False, commands=[], queue_active=None,
                          continue_listening=True)

    mock_router = MagicMock()
    mock_router.route = AsyncMock(side_effect=capture_route)

    pipeline = VoicePipeline(
        asr_service=MagicMock(),
        nlu_service=mock_nlu,
        tts_service=MagicMock(),
        handler_router=mock_router,
    )
    pipeline.respond = AsyncMock()

    conn = MagicMock()
    conn.device_id = "test-dev"
    conn.pending_action = None

    with patch("app.core.pipeline.logger"):
        await pipeline.process_text("删除小星星", "test-dev", conn)

    assert "set_pending_action" in captured_context
    assert callable(captured_context["set_pending_action"])

    # 调用回调验证 pending_action 被设置到 conn 上
    captured_context["set_pending_action"](
        action_type="delete_content",
        data={"content_ids": [1]},
        handler_name="delete",
    )
    assert conn.pending_action is not None
    assert conn.pending_action.action_type == "delete_content"


# ── 18. HandlerRouter 注册 + get_handler_by_name ─────────


def test_router_has_delete_handler():
    """HandlerRouter 正确注册 DeleteHandler"""
    from app.handlers.registry import HandlerRouter

    router = HandlerRouter(
        content_service=MagicMock(),
        tts_service=MagicMock(),
        llm_service=MagicMock(),
    )

    # 意图映射
    assert Intent.DELETE_CONTENT in router._intent_map
    assert isinstance(router._intent_map[Intent.DELETE_CONTENT], DeleteHandler)

    # 名称查找
    h = router.get_handler_by_name("delete")
    assert h is not None
    assert isinstance(h, DeleteHandler)
    assert hasattr(h, "handle_confirmation")

    # 不存在的名称
    assert router.get_handler_by_name("nonexistent") is None


# ── 确认/取消关键词完整性测试 ─────────────────────────────


class TestKeywordCoverage:
    """验证确认和取消关键词的覆盖率和互斥性"""

    @pytest.fixture(autouse=True)
    def setup(self, handler):
        self.handler = handler

    @pytest.mark.parametrize("text", list(CONFIRM_PHRASES) + list(CONFIRM_EXACT))
    def test_all_confirm_keywords_work(self, text):
        """所有确认关键词都能正确匹配"""
        assert self.handler._is_confirm(text), f"'{text}' should be confirm"

    @pytest.mark.parametrize("text", list(CANCEL_PHRASES) + list(CANCEL_EXACT))
    def test_all_cancel_keywords_work(self, text):
        """所有取消关键词都能正确匹配"""
        assert self.handler._is_cancel(text), f"'{text}' should be cancel"

    @pytest.mark.parametrize("text", ["不是", "不好", "不对"])
    def test_negation_not_confirm(self, text):
        """否定短语不能匹配为确认"""
        assert not self.handler._is_confirm(text), f"'{text}' must NOT be confirm"
        assert self.handler._is_cancel(text), f"'{text}' must be cancel"

    @pytest.mark.parametrize("text", [
        "今天天气好", "播放音乐", "几点了", "讲故事", "什么意思",
    ])
    def test_unrelated_is_neither(self, text):
        """无关输入既不是确认也不是取消"""
        assert not self.handler._is_confirm(text), f"'{text}' should NOT confirm"
        assert not self.handler._is_cancel(text), f"'{text}' should NOT cancel"
