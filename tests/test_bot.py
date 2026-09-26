import cv2
import numpy as np
import pytest

from jump_rope_bot import BotConfig, JumpRopeBot
import jump_rope_bot as controller
from vision import RoundGate
from rope_track import VisualPassDetector, RopePosition


def live_frame():
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    cv2.rectangle(frame, (65, 200), (85, 220), (0, 255, 70), -1)
    cv2.rectangle(frame, (800, 400), (840, 450), (0, 240, 255), -1)
    cv2.putText(frame, '20', (45, 105), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)
    return frame


def test_round_end_latches_off_even_if_a_new_game_appears():
    gate = RoundGate()
    live = live_frame()
    assert not gate.observe(live)
    assert not gate.observe(live)
    assert gate.observe(live)
    assert not gate.observe(np.zeros_like(live))
    assert gate.finished
    for _ in range(10):
        assert not gate.observe(live)


def test_jump_button_alone_never_authorizes_click():
    frame = live_frame()
    frame[:240] = 0
    gate = RoundGate()
    for _ in range(10):
        assert not gate.observe(frame)


def test_zero_lives_disables_input():
    gate = RoundGate()
    frame = live_frame()
    for _ in range(3):
        gate.observe(frame)
    frame[190:235, 55:155] = 0
    assert not gate.observe(frame)
    assert gate.finished


def test_rapid_configuration_is_removed():
    with pytest.raises(TypeError):
        BotConfig(strategy='rapid')


def test_non_positive_duration_is_rejected():
    with pytest.raises(ValueError):
        JumpRopeBot().run(0)


def test_observation_mode_does_not_send_input():
    bot = JumpRopeBot(BotConfig(observe_only=True))
    assert not bot.tap_jump(live_frame())
    assert bot.tap_count == 0


def test_default_is_single_round_play():
    assert not JumpRopeBot().config.observe_only


def test_jump_position_is_derived_from_visible_button():
    x, y = RoundGate.jump_position(live_frame())
    assert x == pytest.approx(820/960, abs=.005)
    assert y == pytest.approx(425/540, abs=.005)
    assert RoundGate.jump_position(np.zeros((540, 960, 3), np.uint8)) is None


def measured_detector(positions):
    detector = VisualPassDetector()
    iterator = iter(positions)
    detector.tracker.locate = lambda frame: next(iterator)
    return detector


@pytest.mark.parametrize('step', [.025, .05, .10])
def test_visual_crossing_is_one_event_at_variable_speed(step):
    positions = [RopePosition(h, .8, 0) for h in [-.3, -.25, -.1, .08, .14, .13, .10, .08]]
    detector = measured_detector(positions)
    events = [detector.observe(None, i*step) for i in range(len(positions))]
    assert events == [False, False, False, False, True, False, False, False]


def test_standing_still_never_generates_periodic_clicks():
    detector = measured_detector([RopePosition(.12, .8, 0)]*200)
    assert not any(detector.observe(None, i*.05) for i in range(200))


def test_low_confidence_never_generates_clicks():
    detector = measured_detector([RopePosition(h, .1, 0) for h in [-.3, .08, .14, .10]])
    assert not any(detector.observe(None, i*.05) for i in range(4))


def test_long_observation_gap_does_not_authorize_click():
    detector = measured_detector([RopePosition(h, .8, 0) for h in [-.3, .14, .10]])
    assert not detector.observe(None, 0)
    assert not detector.observe(None, .05)
    assert not detector.observe(None, 2.)


def test_menu_frame_cannot_inject_input(monkeypatch):
    bot = JumpRopeBot(BotConfig(observe_only=False))
    bot._hwnd = 123
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    calls = []
    monkeypatch.setattr(controller.win32api, 'mouse_event', lambda *args: calls.append(args))
    assert not bot.tap_jump(np.zeros_like(live_frame()))
    assert bot._stop.is_set()
    assert calls == []


def test_losing_focus_cannot_inject_input(monkeypatch):
    bot = JumpRopeBot(BotConfig(observe_only=False))
    bot._hwnd = 123
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 456)
    calls = []
    monkeypatch.setattr(controller.win32api, 'mouse_event', lambda *args: calls.append(args))
    assert not bot.tap_jump(live_frame())
    assert calls == []


def test_mouse_released_even_when_hold_is_interrupted(monkeypatch):
    def interrupted(_):
        raise RuntimeError('interrupted')
    bot = JumpRopeBot(BotConfig(observe_only=False), sleeper=interrupted)
    bot._hwnd = 123
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    monkeypatch.setattr(controller.win32gui, 'GetClientRect', lambda _: (0, 0, 960, 540))
    monkeypatch.setattr(controller.win32gui, 'ClientToScreen', lambda _, point: point)
    monkeypatch.setattr(controller.win32api, 'SetCursorPos', lambda _: None)
    calls = []
    monkeypatch.setattr(controller.win32api, 'mouse_event', lambda event, *args: calls.append(event))
    with pytest.raises(RuntimeError, match='interrupted'):
        bot.tap_jump(live_frame())
    assert calls == [controller.win32con.MOUSEEVENTF_LEFTDOWN, controller.win32con.MOUSEEVENTF_LEFTUP]
