"""Startup menu recognition and one-way navigation safety checks."""

from pathlib import Path

import cv2
import pytest

from jump_rope_bot import BotConfig, JumpRopeBot
import jump_rope_bot as controller
from vision import StartupNavigator, StartupScreen


FIXTURES = Path(__file__).parent / "fixtures" / "startup"


def frame(name):
    image = cv2.imread(str(FIXTURES / f"{name}.jpg"))
    assert image is not None
    return image


@pytest.mark.parametrize("name,expected", [
    ("next", "next"), ("ok", "ok"),
    ("event-next", "event_next"), ("play", "play"),
    ("play-resting", "play"),
    ("popup", None), ("game", None), ("finish", None),
])
def test_startup_recognizes_only_known_page_and_button(name, expected):
    assert StartupScreen().identify(frame(name)) == expected


def test_startup_navigation_is_monotonic_and_one_shot():
    navigator = StartupNavigator(StartupScreen())
    for name in ("next", "ok", "event_next", "play"):
        image = frame(name.replace("_", "-"))
        needed = StartupNavigator.CONFIRM_FRAMES[name]
        assert [navigator.observe(image) for _ in range(needed)] == [None] * (needed - 1) + [name]
        navigator.mark_clicked(name)
        assert all(navigator.observe(image) is None for _ in range(10))
    assert not navigator.finished
    navigator.seal()
    assert navigator.finished
    assert all(navigator.observe(frame("next")) is None for _ in range(10))


def test_can_start_on_event_result_without_replaying_earlier_pages():
    navigator = StartupNavigator(StartupScreen())
    image = frame("event-next")
    assert [navigator.observe(image) for _ in range(8)] == [None] * 7 + ["event_next"]
    navigator.mark_clicked("event_next")
    assert all(navigator.observe(image) is None for _ in range(10))
    assert [navigator.observe(frame("play")) for _ in range(8)] == [None] * 7 + ["play"]


def test_ignored_event_next_click_gets_one_visual_retry_only():
    navigator = StartupNavigator(StartupScreen())
    image = frame("event-next")
    assert [navigator.observe(image) for _ in range(8)] == [None] * 7 + ["event_next"]
    navigator.mark_clicked("event_next")
    assert [navigator.observe(image) for _ in range(12)] == [None] * 11 + ["event_next"]
    navigator.mark_clicked("event_next")
    assert all(navigator.observe(image) is None for _ in range(30))
    navigator.seal()
    assert all(navigator.observe(frame("next")) is None for _ in range(30))


def test_ignored_play_gets_one_retry_without_reopening_a_completed_round():
    navigator = StartupNavigator(StartupScreen())
    image = frame('play')
    assert [navigator.observe(image) for _ in range(8)] == [None]*7+['play']
    navigator.mark_clicked('play')
    assert [navigator.observe(image) for _ in range(12)] == [None]*11+['play']
    navigator.mark_clicked('play')
    assert all(navigator.observe(image) is None for _ in range(30))
    assert all(navigator.observe(frame('next')) is None for _ in range(30))
    navigator.seal()
    assert all(navigator.observe(image) is None for _ in range(30))


def test_no_startup_click_after_round_entry_or_in_observe_mode(monkeypatch):
    screen = StartupScreen()
    image = frame("next")
    for config, started in ((BotConfig(auto_start=True), 1.),
                            (BotConfig(auto_start=True, observe_only=True), None)):
        bot = JumpRopeBot(config)
        bot._hwnd = 123
        bot.round_started_at = started
        monkeypatch.setattr(controller.win32gui, "GetForegroundWindow", lambda: 123)
        monkeypatch.setattr(controller.win32api, "mouse_event",
                            lambda *args: pytest.fail("startup click after entry/observe"))
        assert not bot.tap_startup("next", image, screen)


def test_startup_click_is_single_press_and_not_a_jump(monkeypatch):
    durations = []
    bot = JumpRopeBot(BotConfig(auto_start=True), sleeper=durations.append)
    bot._hwnd = 123
    monkeypatch.setattr(controller.win32gui, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(controller.win32gui, "GetClientRect", lambda _: (0, 0, 960, 540))
    monkeypatch.setattr(controller.win32gui, "ClientToScreen", lambda _, point: point)
    monkeypatch.setattr(controller.win32api, "SetCursorPos", lambda _: None)
    presses = []
    monkeypatch.setattr(controller.win32api, "mouse_event",
                        lambda event, *args: presses.append(event))
    assert bot.tap_startup("next", frame("next"), StartupScreen())
    assert presses == [controller.win32con.MOUSEEVENTF_LEFTDOWN,
                       controller.win32con.MOUSEEVENTF_LEFTUP]
    assert bot.input_times == []
    assert bot.menu_actions[0][0] == "next"
    assert durations == [0.12]


def test_startup_navigation_never_reopens_after_monitored_round(monkeypatch, tmp_path):
    sequence = (sum(([frame(name)] * (StartupNavigator.CONFIRM_FRAMES[
        name.replace("-", "_")] + 2) for name in ("next", "ok", "event-next", "play")), [])
                + [frame("game")] * 4 + [frame("next")] * 3)
    frames = iter(sequence)

    class Capture:
        def __init__(self, _hwnd):
            pass

        def grab(self):
            return next(frames)

    class Detector:
        last_score = 0.
        position = None

        def observe(self, _frame, _now):
            return False

    now = [0.]
    bot = JumpRopeBot(BotConfig(auto_start=True, wait_for_round=True,
                                record_path=tmp_path / "startup.mp4",
                                result_postroll=0),
                      clock=lambda: now[0],
                      sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(bot, "focus_game", lambda: setattr(bot, "_hwnd", 123) or 123)
    monkeypatch.setattr(controller, "GameCapture", Capture)
    monkeypatch.setattr(controller, "VisualPassDetector", Detector)
    monkeypatch.setattr(controller.win32gui, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(controller.win32gui, "GetClientRect", lambda _: (0, 0, 960, 540))
    monkeypatch.setattr(controller.win32gui, "ClientToScreen", lambda _, point: point)
    monkeypatch.setattr(controller.win32api, "SetCursorPos", lambda _: None)
    monkeypatch.setattr(controller.win32api, "GetAsyncKeyState", lambda _: 0)
    presses = []
    monkeypatch.setattr(controller.win32api, "mouse_event",
                        lambda event, *args: presses.append(event))

    bot.run()

    assert bot.stop_reason == "round_finished"
    assert [action for action, _ in bot.menu_actions] == ["next", "ok", "event_next", "play"]
    assert bot.input_times == []
    assert len(presses) == 8


def test_single_gameplay_frame_seals_startup_even_without_round_confirmation(monkeypatch):
    images = iter([frame("game")] + [frame("next")] * 10)

    class Capture:
        def __init__(self, _hwnd):
            pass

        def grab(self):
            return next(images)

    now = [0.]
    bot = JumpRopeBot(BotConfig(auto_start=True, wait_for_round=True,
                                startup_timeout=.1),
                      clock=lambda: now[0],
                      sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(bot, "focus_game", lambda: setattr(bot, "_hwnd", 123) or 123)
    monkeypatch.setattr(controller, "GameCapture", Capture)
    monkeypatch.setattr(controller.win32gui, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(controller.win32api, "GetAsyncKeyState", lambda _: 0)
    monkeypatch.setattr(controller.win32api, "mouse_event",
                        lambda *args: pytest.fail("clicked result after gameplay frame"))
    bot.run()
    assert bot.stop_reason == "startup_timeout"
    assert bot.menu_actions == []
