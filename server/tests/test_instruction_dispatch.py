"""
WebSocket 指令分发逻辑单元测试

覆盖场景:
1. non-final 事件重置 _instruction_dispatched
2. final 事件正常 dispatch
3. 同一轮重复 final 被阻止
4. 连续命令（A → B，无唤醒词）都能 dispatch
5. 纯 timer 路径（无 final，1.5s 后触发）
6. _pipeline_active 在 await 之前设置
7. dispatch 时取消 _auto_play_task
8. Idle 事件在 pipeline 活跃时不触发 auto_play
9. Idle 事件在队列活跃时正常触发 auto_play
10. _auto_play_next 在 sleep 后检查 _pipeline_active
11. _on_instruction_complete 空文本时重置 _pipeline_active
12. WOKEN/LISTENING/PROCESSING 状态忽略 instruction
13. pipeline 活跃时拦截云端播放命令
14. non-final 事件取消 _auto_play_task（防止队列指针偏移）
15. 完整场景：歌曲结束 → auto_play 推进 → 用户说"上一首" → 队列指针已偏移
"""

import asyncio
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.models.protocol import Event, PlayingState, ListeningState, Request
from app.api.websocket import (
    handle_event,
    _auto_play_next,
    _on_instruction_complete,
    set_pipeline,
)


# ── Helpers ──────────────────────────────────────────────


def make_instruction_event(
    text: str,
    is_final: bool = False,
    is_stop: bool = False,
) -> Event:
    """创建 instruction 事件（模拟 open-xiaoai ASR 结果）"""
    inner = json.dumps({
        "header": {
            "namespace": "SpeechRecognizer",
            "name": "RecognizeResult",
            "id": str(uuid.uuid4()),
        },
        "payload": {
            "is_final": is_final,
            "results": [{
                "text": text,
                "is_stop": is_stop,
            }],
        },
    })
    return Event(
        id=str(uuid.uuid4()),
        event="instruction",
        data={"NewLine": inner},
    )


def make_playing_event(state: str) -> Event:
    """创建 playing 事件"""
    return Event(id=str(uuid.uuid4()), event="playing", data=state)


def make_cloud_play_event() -> Event:
    """创建云端 AudioPlayer/Play 执行命令"""
    inner = json.dumps({
        "header": {
            "namespace": "AudioPlayer",
            "name": "Play",
            "id": str(uuid.uuid4()),
        },
        "payload": {},
    })
    return Event(
        id=str(uuid.uuid4()),
        event="instruction",
        data={"NewLine": inner},
    )


async def drain():
    """让 event loop 处理所有待执行 task"""
    await asyncio.sleep(0.05)


# ── 1. _instruction_dispatched 重置逻辑 ──────────────────


@pytest.mark.asyncio
async def test_nonfinal_resets_instruction_dispatched(conn, mock_manager, mock_pipeline):
    """non-final 事件应重置 _instruction_dispatched，允许后续 final dispatch"""
    # 模拟上一轮留下的 True
    conn._instruction_dispatched = True

    await handle_event(conn, make_instruction_event("上一首", is_final=False))

    assert conn._instruction_dispatched is False
    assert conn._instruction_text == "上一首"
    assert conn._instruction_timer is not None

    # 清理 timer
    conn._instruction_timer.cancel()


@pytest.mark.asyncio
async def test_nonfinal_starts_debounce_timer(conn, mock_manager, mock_pipeline):
    """non-final 事件应启动去抖定时器"""
    await handle_event(conn, make_instruction_event("播放音乐", is_final=False))

    assert conn._instruction_timer is not None
    assert not conn._instruction_timer.done()

    conn._instruction_timer.cancel()


# ── 2. Final 事件 dispatch ──────────────────────────────


@pytest.mark.asyncio
async def test_final_dispatches_pipeline(conn, mock_manager, mock_pipeline):
    """non-final → final 应正常 dispatch 到 pipeline"""
    await handle_event(conn, make_instruction_event("上一首", is_final=False))
    await handle_event(conn, make_instruction_event("上一首", is_stop=True))

    assert conn._instruction_dispatched is True

    # 等待 _on_instruction_complete 执行完
    await drain()

    mock_pipeline.process_text.assert_called_once_with(
        "上一首", "test-device", conn
    )


@pytest.mark.asyncio
async def test_final_cancels_timer(conn, mock_manager, mock_pipeline):
    """final 事件应取消去抖定时器"""
    await handle_event(conn, make_instruction_event("暂停", is_final=False))
    timer = conn._instruction_timer
    assert timer is not None

    await handle_event(conn, make_instruction_event("暂停", is_stop=True))

    # cancel() 是异步的，需要 drain 让 CancelledError 传播
    await drain()

    assert timer.cancelled() or timer.done()


@pytest.mark.asyncio
async def test_final_sets_pipeline_active_before_await(conn, mock_manager, mock_pipeline):
    """_pipeline_active 必须在 send_request(abort) 之前设置为 True

    这是防止竞态的关键：如果 Idle 事件在 await send_request 期间到达，
    _pipeline_active=True 会阻止 _auto_play_next 被触发。
    """
    pipeline_active_during_send = []

    async def capture_state(*args, **kwargs):
        # 记录每次 send_request 调用时的 _pipeline_active 状态
        pipeline_active_during_send.append(conn._pipeline_active)

    mock_manager.send_request = AsyncMock(side_effect=capture_state)

    await handle_event(conn, make_instruction_event("上一首", is_final=False))
    await handle_event(conn, make_instruction_event("上一首", is_stop=True))

    # 第一个 send_request 是 dispatch 路径中的 abort_xiaoai（line 333）
    # 此时 _pipeline_active 应已为 True（在 line 331 设置）
    assert len(pipeline_active_during_send) >= 1
    assert pipeline_active_during_send[0] is True, (
        f"_pipeline_active should be True during first send_request, "
        f"got sequence: {pipeline_active_during_send}"
    )

    await drain()


# ── 3. 重复 final 阻止 ──────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_final_blocked(conn, mock_manager, mock_pipeline):
    """同一轮重复 final（is_final=true 跟在 is_stop=true 后）应被阻止"""
    # non-final → final (is_stop)
    await handle_event(conn, make_instruction_event("上一首", is_final=False))
    await handle_event(conn, make_instruction_event("上一首", is_stop=True))

    await drain()
    assert mock_pipeline.process_text.call_count == 1

    # 同一轮再来一个 is_final=true（中间无 non-final）
    await handle_event(conn, make_instruction_event("上一首", is_final=True))

    await drain()
    # 仍然只处理了一次
    assert mock_pipeline.process_text.call_count == 1


# ── 4. 连续命令（无唤醒词）──────────────────────────────


@pytest.mark.asyncio
async def test_back_to_back_commands_both_dispatch(conn, mock_manager, mock_pipeline):
    """连续两个命令（A → B）无唤醒词，都应正常 dispatch"""
    # Command A
    await handle_event(conn, make_instruction_event("播放音乐", is_final=False))
    await handle_event(conn, make_instruction_event("播放音乐", is_stop=True))
    await drain()

    assert mock_pipeline.process_text.call_count == 1
    assert conn._pipeline_active is False  # A 处理完毕

    # Command B — non-final 重置 _instruction_dispatched
    await handle_event(conn, make_instruction_event("下一首", is_final=False))
    assert conn._instruction_dispatched is False

    await handle_event(conn, make_instruction_event("下一首", is_stop=True))
    await drain()

    assert mock_pipeline.process_text.call_count == 2
    mock_pipeline.process_text.assert_called_with("下一首", "test-device", conn)


@pytest.mark.asyncio
async def test_three_consecutive_commands(conn, mock_manager, mock_pipeline):
    """三个连续命令都能正常 dispatch"""
    commands = ["播放音乐", "下一首", "暂停"]

    for cmd in commands:
        await handle_event(conn, make_instruction_event(cmd, is_final=False))
        await handle_event(conn, make_instruction_event(cmd, is_stop=True))
        await drain()

    assert mock_pipeline.process_text.call_count == 3


# ── 5. Timer 路径 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_timer_fires_without_final(conn, mock_manager, mock_pipeline):
    """只有 non-final 事件时，1.5s 定时器应触发 dispatch"""
    await handle_event(conn, make_instruction_event("暂停", is_final=False))

    assert conn._instruction_dispatched is False
    assert not mock_pipeline.process_text.called

    # 等 timer 触发（1.5s + 余量）
    await asyncio.sleep(1.7)

    assert conn._instruction_dispatched is True
    mock_pipeline.process_text.assert_called_once_with("暂停", "test-device", conn)


@pytest.mark.asyncio
async def test_timer_blocked_if_final_already_dispatched(conn, mock_manager, mock_pipeline):
    """如果 final 已 dispatch，timer 应跳过（不重复处理）"""
    # non-final 启动 timer
    await handle_event(conn, make_instruction_event("上一首", is_final=False))
    # final 立即 dispatch
    await handle_event(conn, make_instruction_event("上一首", is_stop=True))

    await drain()
    assert mock_pipeline.process_text.call_count == 1

    # 等 timer 到期（即使它没被 cancel 也应被 guard 阻止）
    await asyncio.sleep(1.7)

    # 仍然只处理一次
    assert mock_pipeline.process_text.call_count == 1


# ── 6. _auto_play_task 取消 ─────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_cancels_auto_play_task(conn, mock_manager, mock_pipeline):
    """final dispatch 应在 await 之前同步取消 _auto_play_task"""
    async def fake_auto_play():
        await asyncio.sleep(100)

    task = asyncio.create_task(fake_auto_play())
    conn._auto_play_task = task
    conn._queue_active = True

    # 让 task 进入 sleep（必须 yield 一次让它开始执行）
    await asyncio.sleep(0)

    # dispatch
    await handle_event(conn, make_instruction_event("下一首", is_final=False))
    await handle_event(conn, make_instruction_event("下一首", is_stop=True))

    # conn._auto_play_task 应被清为 None
    assert conn._auto_play_task is None

    # 让 CancelledError 传播
    await drain()

    # 原始 task 引用应已被取消
    assert task.done()
    assert task.cancelled()


# ── 7. Idle 事件 + _auto_play_next ──────────────────────


@pytest.mark.asyncio
async def test_idle_no_autoplay_when_pipeline_active(conn, mock_manager, mock_pipeline):
    """pipeline 活跃时，Idle 事件不应创建 _auto_play_next task"""
    conn._pipeline_active = True
    conn._queue_active = True

    await handle_event(conn, make_playing_event("Idle"))

    assert conn._auto_play_task is None


@pytest.mark.asyncio
async def test_idle_no_autoplay_when_queue_inactive(conn, mock_manager, mock_pipeline):
    """队列未激活时，Idle 事件不应创建 _auto_play_next task"""
    conn._pipeline_active = False
    conn._queue_active = False

    await handle_event(conn, make_playing_event("Idle"))

    assert conn._auto_play_task is None


@pytest.mark.asyncio
async def test_idle_triggers_autoplay_when_conditions_met(conn, mock_manager, mock_pipeline):
    """队列活跃 + pipeline 空闲时，Idle 应创建 _auto_play_next task"""
    conn._queue_active = True
    conn._pipeline_active = False

    await handle_event(conn, make_playing_event("Idle"))

    assert conn._auto_play_task is not None
    assert not conn._auto_play_task.done()

    conn._auto_play_task.cancel()
    try:
        await conn._auto_play_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_auto_play_next_respects_pipeline_active(conn, mock_manager, mock_pipeline):
    """_auto_play_next 在 1.5s sleep 后应检查 _pipeline_active"""
    conn._queue_active = True
    conn._pipeline_active = False
    conn.playing_state = PlayingState.IDLE

    pipeline = mock_pipeline
    pipeline.play_queue_service.get_next = AsyncMock(return_value=1)
    pipeline.content_service.get_content_by_id = AsyncMock(
        return_value={"title": "test", "play_url": "http://test.mp3"}
    )
    pipeline.content_service.increment_play_count = AsyncMock()

    # 启动 auto_play_next
    task = asyncio.create_task(_auto_play_next(conn, pipeline))

    # 在 sleep 期间模拟 pipeline 启动
    await asyncio.sleep(0.1)
    conn._pipeline_active = True

    # 等 auto_play 的 sleep 结束
    await asyncio.sleep(1.6)

    # 不应调用 get_next
    pipeline.play_queue_service.get_next.assert_not_called()

    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_auto_play_next_respects_queue_deactivated(conn, mock_manager, mock_pipeline):
    """_auto_play_next 在 sleep 后 queue 被关闭应退出"""
    conn._queue_active = True
    conn._pipeline_active = False
    conn.playing_state = PlayingState.IDLE

    pipeline = mock_pipeline
    pipeline.play_queue_service.get_next = AsyncMock(return_value=1)

    task = asyncio.create_task(_auto_play_next(conn, pipeline))

    # sleep 期间关闭队列
    await asyncio.sleep(0.1)
    conn._queue_active = False

    await asyncio.sleep(1.6)

    pipeline.play_queue_service.get_next.assert_not_called()

    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── 8. _on_instruction_complete 边界 ────────────────────


@pytest.mark.asyncio
async def test_on_instruction_complete_empty_text_resets_pipeline(
    conn, mock_manager, mock_pipeline
):
    """text 为空时，_on_instruction_complete 应重置 _pipeline_active 并退出"""
    conn._instruction_text = ""
    conn._pipeline_active = True  # dispatch 路径提前设置

    await _on_instruction_complete(conn)

    assert conn._pipeline_active is False
    mock_pipeline.process_text.assert_not_called()


@pytest.mark.asyncio
async def test_on_instruction_complete_none_text_resets_pipeline(
    conn, mock_manager, mock_pipeline
):
    """text 为 None 时同样重置"""
    conn._instruction_text = None
    conn._pipeline_active = True

    await _on_instruction_complete(conn)

    assert conn._pipeline_active is False


@pytest.mark.asyncio
async def test_on_instruction_complete_resets_pipeline_active_on_finish(
    conn, mock_manager, mock_pipeline
):
    """正常处理完毕后 _pipeline_active 应重置为 False"""
    conn._instruction_text = "下一首"
    conn._pipeline_active = False

    await _on_instruction_complete(conn)

    assert conn._pipeline_active is False
    mock_pipeline.process_text.assert_called_once()


@pytest.mark.asyncio
async def test_on_instruction_complete_resets_pipeline_active_on_error(
    conn, mock_manager, mock_pipeline
):
    """pipeline 异常时 _pipeline_active 仍应重置"""
    conn._instruction_text = "出错测试"
    mock_pipeline.process_text = AsyncMock(side_effect=RuntimeError("模拟异常"))

    await _on_instruction_complete(conn)

    assert conn._pipeline_active is False


# ── 9. 状态机保护 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_instruction_ignored_during_audio_states(conn, mock_manager, mock_pipeline):
    """WOKEN/LISTENING/PROCESSING 状态下 instruction 事件应被忽略"""
    for state in [
        ListeningState.WOKEN,
        ListeningState.LISTENING,
        ListeningState.PROCESSING,
    ]:
        conn.state = state
        conn._instruction_dispatched = False
        conn._instruction_text = None

        await handle_event(conn, make_instruction_event("上一首", is_stop=True))

        assert conn._instruction_dispatched is False
        assert conn._instruction_text is None


@pytest.mark.asyncio
async def test_instruction_processed_in_idle_state(conn, mock_manager, mock_pipeline):
    """IDLE 状态下 instruction 正常处理"""
    conn.state = ListeningState.IDLE

    await handle_event(conn, make_instruction_event("上一首", is_final=False))
    await handle_event(conn, make_instruction_event("上一首", is_stop=True))

    assert conn._instruction_dispatched is True

    await drain()
    mock_pipeline.process_text.assert_called_once()


# ── 10. 云端命令拦截 ────────────────────────────────────


@pytest.mark.asyncio
async def test_cloud_playback_intercepted_during_pipeline(conn, mock_manager, mock_pipeline):
    """pipeline 活跃时，云端 AudioPlayer/Play 命令应被拦截"""
    conn._pipeline_active = True

    await handle_event(conn, make_cloud_play_event())

    # 应发送 abort + pause 拦截云端
    assert mock_manager.send_request.call_count == 2


@pytest.mark.asyncio
async def test_cloud_playback_not_intercepted_when_idle(conn, mock_manager, mock_pipeline):
    """pipeline 空闲时，云端命令不应被拦截"""
    conn._pipeline_active = False

    await handle_event(conn, make_cloud_play_event())

    # 不应触发拦截（cloud playback 命令无 RecognizeResult，不走 text 路径）
    mock_manager.send_request.assert_not_called()


# ── 11. Playing 状态拦截 ────────────────────────────────


@pytest.mark.asyncio
async def test_playing_intercepted_during_pipeline(conn, mock_manager, mock_pipeline):
    """pipeline 活跃时，云端触发的 Playing 事件应被打断"""
    conn._pipeline_active = True

    await handle_event(conn, make_playing_event("Playing"))

    # 应发送 abort + pause 打断云端播放
    assert mock_manager.send_request.call_count == 2


@pytest.mark.asyncio
async def test_playing_not_intercepted_when_idle(conn, mock_manager, mock_pipeline):
    """pipeline 空闲时，Playing 事件正常处理（不拦截）"""
    conn._pipeline_active = False

    await handle_event(conn, make_playing_event("Playing"))

    assert conn.playing_state == PlayingState.PLAYING
    mock_manager.send_request.assert_not_called()


# ── 12. 完整场景：播放歌曲 → 说"上一首" ─────────────────


@pytest.mark.asyncio
async def test_full_scenario_previous_track(conn, mock_manager, mock_pipeline):
    """完整场景：歌曲播放中 → 用户说"上一首" → 正确处理

    模拟真实日志中的事件序列:
    1. 正在播放（queue_active=True）
    2. 收到 non-final "上一首"
    3. 收到 final "上一首"（is_stop=True）
    4. 收到 duplicate final（is_final=True）— 应被阻止
    5. 收到 cloud PlaybackController/Prev — 应被拦截
    6. 播放器 Idle — pipeline 活跃，不触发 auto_play
    """
    # 初始状态：正在播放
    conn._queue_active = True
    conn.playing_state = PlayingState.PLAYING

    # Step 1: non-final
    await handle_event(conn, make_instruction_event("上一首", is_final=False))
    assert conn._instruction_dispatched is False

    # Step 2: final (is_stop=True)
    await handle_event(conn, make_instruction_event("上一首", is_stop=True))
    assert conn._instruction_dispatched is True
    assert conn._pipeline_active is True

    # Step 3: duplicate final (is_final=True) — 应被阻止
    initial_send_count = mock_manager.send_request.call_count
    await handle_event(conn, make_instruction_event("上一首", is_final=True))
    # send_request 调用次数不应增加（duplicate 被忽略）
    assert mock_manager.send_request.call_count == initial_send_count

    # Step 4: cloud PlaybackController/Prev — pipeline 活跃，应被拦截
    await handle_event(conn, make_cloud_play_event())
    # 拦截应发送 2 个请求（abort + pause）
    assert mock_manager.send_request.call_count == initial_send_count + 2

    # Step 5: Idle — pipeline 活跃，不触发 auto_play
    await handle_event(conn, make_playing_event("Idle"))
    assert conn._auto_play_task is None

    # 等 pipeline 完成
    await drain()
    mock_pipeline.process_text.assert_called_once_with("上一首", "test-device", conn)
    assert conn._pipeline_active is False


@pytest.mark.asyncio
async def test_full_scenario_consecutive_next_previous(conn, mock_manager, mock_pipeline):
    """完整场景：连续 "下一首" → "上一首" 都能处理"""
    conn._queue_active = True

    # "下一首"
    await handle_event(conn, make_instruction_event("下一首", is_final=False))
    await handle_event(conn, make_instruction_event("下一首", is_stop=True))
    await drain()

    assert mock_pipeline.process_text.call_count == 1
    mock_pipeline.process_text.assert_called_with("下一首", "test-device", conn)
    assert conn._pipeline_active is False

    # "上一首"
    await handle_event(conn, make_instruction_event("上一首", is_final=False))
    assert conn._instruction_dispatched is False  # 被 non-final 重置

    await handle_event(conn, make_instruction_event("上一首", is_stop=True))
    await drain()

    assert mock_pipeline.process_text.call_count == 2
    mock_pipeline.process_text.assert_called_with("上一首", "test-device", conn)


# ── 14. non-final 事件取消 _auto_play_task ──────────────────


@pytest.mark.asyncio
async def test_nonfinal_cancels_auto_play_task(conn, mock_manager, mock_pipeline):
    """non-final 事件应立即取消 _auto_play_task，防止队列指针被自动推进

    场景：歌曲结束 → auto_play_task 创建(1.5s 延迟) → 用户开口说话(non-final 到达)
    → auto_play_task 应在推进队列前被取消
    """
    conn._queue_active = True

    # 创建一个模拟的 auto_play task（类似歌曲结束后 Idle 事件创建的）
    cancel_observed = asyncio.Event()

    async def fake_auto_play():
        try:
            await asyncio.sleep(10)  # 模拟 1.5s 等待
        except asyncio.CancelledError:
            cancel_observed.set()
            raise

    conn._auto_play_task = asyncio.create_task(fake_auto_play())
    await asyncio.sleep(0)  # 让 task 开始执行

    # 用户开始说话 → non-final 事件到达
    await handle_event(conn, make_instruction_event("上一首", is_final=False))

    # auto_play_task 应该已被取消
    assert conn._auto_play_task is None
    # 等待 cancel 传播
    await asyncio.sleep(0.01)
    assert cancel_observed.is_set(), "_auto_play_task 应在 non-final 事件时被取消"


# ── 15. 完整场景：歌曲结束 → auto_play 推进 → 用户说话 ──────────────


@pytest.mark.asyncio
async def test_full_scenario_auto_play_race_with_previous(conn, mock_manager, mock_pipeline):
    """完整场景复现：歌曲结束后 auto_play 应被用户语音取消，不推进队列

    时间线（真实设备日志）：
    1. "下一首" → 播放 id=10（大城小爱，index=1）
    2. 歌曲结束 → Idle → _auto_play_task 创建（1.5s 后推进到 index=2）
    3. 用户说"上一首" → non-final 到达
    4. 期望：auto_play_task 被取消，不推进队列
    5. final "上一首" → dispatch → 从 index=1 回退到 index=0（天地龙鳞）
    """
    conn._queue_active = True
    conn.playing_state = PlayingState.IDLE

    # 步骤 1：模拟 auto_play_task 已创建（歌曲结束后 Idle 事件触发）
    auto_play_advanced = asyncio.Event()

    async def fake_auto_play_that_advances():
        """模拟 _auto_play_next：sleep 后推进队列"""
        try:
            await asyncio.sleep(0.1)  # 缩短等待时间
            # 如果执行到这里，说明没被取消 → 队列被错误推进
            auto_play_advanced.set()
        except asyncio.CancelledError:
            raise

    conn._auto_play_task = asyncio.create_task(fake_auto_play_that_advances())
    await asyncio.sleep(0)  # 让 task 进入 sleep

    # 步骤 2：用户开始说"上一首"（non-final 事件到达）
    await handle_event(conn, make_instruction_event("上一首", is_final=False))

    # 步骤 3：验证 auto_play_task 已被取消
    assert conn._auto_play_task is None

    # 步骤 4：等待足够时间，确认 auto_play 没有推进队列
    await asyncio.sleep(0.15)
    assert not auto_play_advanced.is_set(), \
        "auto_play_task 不应推进队列（用户已开始说话）"

    # 步骤 5：final "上一首" 正常 dispatch
    await handle_event(conn, make_instruction_event("上一首", is_stop=True))
    await drain()

    mock_pipeline.process_text.assert_called_once_with("上一首", "test-device", conn)
