"""
StoryHandler 单元测试

覆盖场景:
1.  DB 命中 → 直接播放（行为不变）
2.  DB 未命中 → LLM 生成 → 播报提示 + 背景音乐 + 故事播放
3.  DB 未命中 + 无 context → 静默等待后播放（降级）
4.  LLM/TTS 失败 → 返回"没有找到"提示（不崩溃）
5.  输入超长名称 → 截断到 50 字符
6.  输入含敏感词 → 拒绝生成，返回 None
7.  LLM 输出含敏感词 → 安全过滤拦截，返回 None
8.  音频持久化成功 → DB 存 MinIO 路径
9.  音频持久化失败 → 降级存原始 URL
10. _get_ai_category_id 并发 → 锁保护，不重复创建
11. 第二次请求同名故事 → DB 命中（走缓存）
12. PLAY_STORY / PLAY_STORY_CATEGORY 意图不触发生成
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from app.core.nlu import Intent, NLUResult
from app.models.database import ContentType
from app.handlers.story import StoryHandler, _MAX_STORY_NAME_LENGTH


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_content_service():
    svc = MagicMock()
    svc.get_random_story = AsyncMock(return_value=None)
    svc.get_random_music = AsyncMock(return_value=None)
    svc.get_content_by_name = AsyncMock(return_value=None)
    svc.increment_play_count = AsyncMock()
    svc.create_content = AsyncMock(return_value={"id": 99})
    svc.session_factory = MagicMock()  # will be configured per test
    svc.minio = MagicMock()
    svc.minio.upload_bytes = AsyncMock(return_value="stories/ai_generated/test.mp3")
    return svc


@pytest.fixture
def mock_tts_service():
    svc = MagicMock()
    svc.synthesize_to_url = AsyncMock(return_value="https://tts.example.com/story.mp3")
    return svc


@pytest.fixture
def mock_llm_service():
    svc = MagicMock()
    svc.chat = AsyncMock(return_value="从前有一只小兔子，它住在森林里。有一天它遇到了一只小鸟...")
    return svc


@pytest.fixture
def handler(mock_content_service, mock_tts_service, mock_llm_service):
    return StoryHandler(
        content_service=mock_content_service,
        tts_service=mock_tts_service,
        llm_service=mock_llm_service,
    )


@pytest.fixture
def context():
    """提供 play_tts 和 play_url 回调的 context"""
    return {
        "play_tts": AsyncMock(),
        "play_url": AsyncMock(),
    }


def make_nlu(intent: Intent, slots: dict = None, raw_text: str = "") -> NLUResult:
    return NLUResult(intent=intent, slots=slots or {}, confidence=0.95, raw_text=raw_text)


# ── 1. DB 命中 → 直接播放 ───────────────────────────────


@pytest.mark.asyncio
async def test_db_hit_returns_content(handler, mock_content_service):
    """DB 命中 → 返回故事，不触发 LLM"""
    mock_content_service.get_content_by_name.return_value = {
        "id": 1,
        "title": "小星星",
        "play_url": "https://minio/stories/xiaoxingxing.mp3",
    }

    result = await handler.handle(
        make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小星星"}),
        "dev-1",
    )

    assert result.play_url == "https://minio/stories/xiaoxingxing.mp3"
    assert "小星星" in result.text
    mock_content_service.increment_play_count.assert_called_once_with(1)
    handler.llm_service.chat.assert_not_called()


# ── 2. DB 未命中 → LLM 生成完整流程 ──────────────────────


@pytest.mark.asyncio
async def test_db_miss_triggers_generation(handler, mock_content_service, context):
    """DB 未命中 → 播报提示 → 背景音乐 → LLM 生成 → TTS → 返回故事"""
    mock_content_service.get_content_by_name.return_value = None
    mock_content_service.get_random_music.return_value = {
        "play_url": "https://minio/music/bgm.mp3"
    }

    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        # Mock httpx download for _persist_audio
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-audio-bytes"
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        result = await handler.handle(
            make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小星星"}),
            "dev-1",
            context,
        )

    assert result.play_url is not None
    assert "小星星" in result.text

    # 验证 play_tts 被调用（播报"正在创作"）
    context["play_tts"].assert_called_once()
    call_text = context["play_tts"].call_args[0][0]
    assert "正在为你创作" in call_text

    # 验证 play_url 被调用（背景音乐）
    context["play_url"].assert_called_once_with("https://minio/music/bgm.mp3")

    # 验证 LLM 和 TTS 被调用
    handler.llm_service.chat.assert_called_once()
    handler.tts_service.synthesize_to_url.assert_called_once()


# ── 3. 无 context → 静默等待后播放 ──────────────────────


@pytest.mark.asyncio
async def test_generation_without_context(handler, mock_content_service):
    """无 context 时跳过播报和背景音乐，LLM 仍能生成"""
    mock_content_service.get_content_by_name.return_value = None

    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.content = b"audio"
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        result = await handler.handle(
            make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "龟兔赛跑"}),
            "dev-1",
            context=None,
        )

    assert result.play_url is not None
    assert "龟兔赛跑" in result.text
    handler.llm_service.chat.assert_called_once()


# ── 4. LLM/TTS 失败 → 优雅降级 ──────────────────────────


@pytest.mark.asyncio
async def test_tts_failure_returns_not_found(handler, mock_content_service):
    """TTS 合成异常 → _generate_story 返回 None → 用户看到'没有找到'"""
    mock_content_service.get_content_by_name.return_value = None
    handler.tts_service.synthesize_to_url = AsyncMock(
        side_effect=Exception("语音合成服务不可用")
    )

    result = await handler.handle(
        make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小恐龙"}),
        "dev-1",
    )

    assert "没有找到" in result.text
    assert result.play_url is None


@pytest.mark.asyncio
async def test_llm_failure_returns_not_found(handler, mock_content_service):
    """LLM 调用异常 → 同样优雅降级"""
    mock_content_service.get_content_by_name.return_value = None
    handler.llm_service.chat = AsyncMock(side_effect=Exception("LLM timeout"))

    result = await handler.handle(
        make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小猫钓鱼"}),
        "dev-1",
    )

    assert "没有找到" in result.text
    assert result.play_url is None


# ── 5. 超长名称截断 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_long_name_truncated(handler, mock_content_service):
    """超长名称被截断到 _MAX_STORY_NAME_LENGTH"""
    mock_content_service.get_content_by_name.return_value = None

    long_name = "很" * 100  # 100 chars
    assert len(long_name) > _MAX_STORY_NAME_LENGTH

    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.content = b"audio"
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        result = await handler.handle(
            make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": long_name}),
            "dev-1",
        )

    # LLM 应被调用（名称被截断后通过安全检查）
    handler.llm_service.chat.assert_called_once()
    prompt = handler.llm_service.chat.call_args[0][0]
    # 截断后的名称应在 prompt 中
    assert "很" * _MAX_STORY_NAME_LENGTH in prompt


# ── 6. 敏感词名称被拒绝 ──────────────────────────────────


@pytest.mark.asyncio
async def test_unsafe_name_rejected(handler, mock_content_service):
    """包含敏感词的故事名称 → 生成被拒绝"""
    mock_content_service.get_content_by_name.return_value = None

    result = await handler.handle(
        make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "暴力大王"}),
        "dev-1",
    )

    assert "没有找到" in result.text
    handler.llm_service.chat.assert_not_called()


# ── 7. LLM 输出含敏感词 → 安全过滤 ──────────────────────


@pytest.mark.asyncio
async def test_unsafe_llm_output_filtered(handler, mock_content_service):
    """LLM 生成含敏感内容 → 被安全过滤 → 返回 None"""
    mock_content_service.get_content_by_name.return_value = None
    handler.llm_service.chat = AsyncMock(return_value="从前有一个暴力的怪物在恐怖森林里...")

    result = await handler.handle(
        make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小森林"}),
        "dev-1",
    )

    assert "没有找到" in result.text
    handler.tts_service.synthesize_to_url.assert_not_called()


# ── 8. 音频持久化成功 → DB 存 MinIO 路径 ────────────────


@pytest.mark.asyncio
async def test_persist_audio_success(handler):
    """_persist_audio 成功时返回 MinIO 对象路径"""
    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.content = b"fake-mp3-bytes"
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        result = await handler._persist_audio("小星星", "https://tts.example.com/audio.mp3")

    # 返回的应该是 MinIO 路径，不是原始 URL
    assert result.startswith("stories/ai_generated/")
    assert result.endswith(".mp3")
    handler.content_service.minio.upload_bytes.assert_called_once()


# ── 9. 音频持久化失败 → 降级存原始 URL ──────────────────


@pytest.mark.asyncio
async def test_persist_audio_fallback_on_failure(handler):
    """_persist_audio 失败时返回原始 URL（降级）"""
    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        result = await handler._persist_audio("test", "https://tts.example.com/x.mp3")

    assert result == "https://tts.example.com/x.mp3"


# ── 10. _get_ai_category_id 并发安全 ───────────────────


@pytest.mark.asyncio
async def test_get_ai_category_id_concurrent(handler, mock_content_service):
    """并发调用 _get_ai_category_id → 锁保护，只创建一次"""
    call_count = 0

    # 模拟 session_factory context manager
    class FakeSession:
        async def execute(self, query):
            result = MagicMock()
            result.scalar_one_or_none.return_value = None  # 模拟"不存在"
            return result

        def add(self, obj):
            nonlocal call_count
            call_count += 1
            obj.id = 42

        async def commit(self):
            pass

        async def refresh(self, obj):
            obj.id = 42

    class FakeSessionCtx:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *args):
            pass

    mock_content_service.session_factory.return_value = FakeSessionCtx()

    # 重置缓存
    handler._ai_category_id = None

    results = await asyncio.gather(
        handler._get_ai_category_id(),
        handler._get_ai_category_id(),
        handler._get_ai_category_id(),
    )

    # 所有结果相同
    assert all(r == 42 for r in results)
    # 只创建了一次（锁保护 + double-check）
    assert call_count == 1


# ── 11. 重复请求走 DB 缓存 ──────────────────────────────


@pytest.mark.asyncio
async def test_second_request_hits_db(handler, mock_content_service):
    """第二次请求同名故事 → DB 命中，不触发 LLM"""
    # 第一次：DB 未命中
    mock_content_service.get_content_by_name.return_value = None

    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.content = b"audio"
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        r1 = await handler.handle(
            make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小青蛙"}),
            "dev-1",
        )

    assert r1.play_url is not None
    assert handler.llm_service.chat.call_count == 1

    # 第二次：DB 命中
    mock_content_service.get_content_by_name.return_value = {
        "id": 99,
        "title": "小青蛙",
        "play_url": "https://minio/stories/ai_generated/xiaoquwa.mp3",
    }

    r2 = await handler.handle(
        make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小青蛙"}),
        "dev-1",
    )

    assert r2.play_url is not None
    # LLM 仍然只被调用了一次
    assert handler.llm_service.chat.call_count == 1


# ── 12. 其他意图不触发生成 ──────────────────────────────


@pytest.mark.asyncio
async def test_play_story_random_no_generation(handler, mock_content_service):
    """PLAY_STORY 意图（随机播放）→ 不触发 LLM 生成"""
    mock_content_service.get_random_story.return_value = None

    result = await handler.handle(make_nlu(Intent.PLAY_STORY), "dev-1")

    assert "没有找到" in result.text
    handler.llm_service.chat.assert_not_called()


@pytest.mark.asyncio
async def test_play_story_category_no_generation(handler, mock_content_service):
    """PLAY_STORY_CATEGORY 意图 → 不触发 LLM 生成"""
    mock_content_service.get_random_story.return_value = None

    result = await handler.handle(
        make_nlu(Intent.PLAY_STORY_CATEGORY, {"category": "童话"}),
        "dev-1",
    )

    assert "没有找到" in result.text
    handler.llm_service.chat.assert_not_called()


# ── 13. DB 保存失败不影响播放 ────────────────────────────


@pytest.mark.asyncio
async def test_db_save_failure_still_plays(handler, mock_content_service):
    """create_content 失败 → 故事仍然正常返回给用户"""
    mock_content_service.get_content_by_name.return_value = None
    mock_content_service.create_content = AsyncMock(
        side_effect=Exception("DB connection lost")
    )

    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.content = b"audio"
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        # 需要给 _get_ai_category_id 设置缓存避免 session_factory 调用
        handler._ai_category_id = 1

        result = await handler.handle(
            make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小火车"}),
            "dev-1",
        )

    # 即使 DB 保存失败，用户仍然能听到故事
    assert result.play_url is not None
    assert "小火车" in result.text


# ── 14. 背景音乐获取失败不影响生成 ────────────────────────


@pytest.mark.asyncio
async def test_bgm_failure_still_generates(handler, mock_content_service, context):
    """背景音乐获取失败 → 跳过 BGM，LLM 仍正常生成"""
    mock_content_service.get_content_by_name.return_value = None
    mock_content_service.get_random_music = AsyncMock(
        side_effect=Exception("music DB error")
    )

    with patch("app.handlers.story.httpx.AsyncClient") as mock_httpx:
        mock_resp = MagicMock()
        mock_resp.content = b"audio"
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.return_value = mock_client

        result = await handler.handle(
            make_nlu(Intent.PLAY_STORY_BY_NAME, {"story_name": "小蜜蜂"}),
            "dev-1",
            context,
        )

    assert result.play_url is not None
    # play_url 回调未被调用（BGM 失败）
    context["play_url"].assert_not_called()
    # 但 play_tts 仍被调用
    context["play_tts"].assert_called_once()
