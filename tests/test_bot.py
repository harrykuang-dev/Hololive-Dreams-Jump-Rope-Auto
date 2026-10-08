import cv2
import numpy as np
import pytest

from jump_rope_bot import BotConfig, JumpRopeBot
import jump_rope_bot as controller
from vision import RoundGate
from rope_geometry import VisualPassDetector, RopePosition


def live_frame():
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    cv2.rectangle(frame, (65, 200), (85, 220), (0, 255, 70), -1)
    cv2.rectangle(frame, (790, 390), (850, 460), (255, 90, 0), -1)
    cv2.rectangle(frame, (800, 400), (840, 450), (0, 240, 255), -1)
    cv2.putText(frame, '20', (45, 105), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)
    cv2.fillConvexPoly(frame, np.array([[540, 193], [532, 205], [548, 205]]), (0, 240, 255))
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


def test_player_leaving_lineup_disables_input():
    frame = live_frame()
    assert RoundGate.player_ready(frame)
    frame[190:210, 530:550] = 0
    assert not RoundGate.player_ready(frame)


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


@pytest.mark.parametrize('f9', [False, True])
def test_launch_banner_waits_without_input_and_has_no_fixed_f9(monkeypatch, f9):
    calls = []
    bot = JumpRopeBot(BotConfig(observe_only=True), sleeper=lambda _: None)

    class Capture:
        def __init__(self, _): pass
        def grab(self):
            calls.append(1)
            if len(calls) < 3:
                raise controller.TemporaryCaptureOverlayError('launch banner')
            bot.stop()
            return np.zeros((540, 960, 3), np.uint8)

    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123))
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState',
                        lambda _: 0x8000 if f9 and calls else 0)
    monkeypatch.setattr(bot, 'tap_jump', lambda _: pytest.fail('input under launch banner'))
    bot.run()
    assert bot.tap_count == 0
    assert len(calls) == 3
    assert bot.stop_reason == 'stopped'


def test_default_is_single_round_play():
    assert not JumpRopeBot().config.observe_only


@pytest.mark.parametrize('startup_timeout,first_frame,expected_wait', [
    (120, False, 60), (2, False, 2), (120, True, 0),
])
def test_launch_overlay_deadline_and_no_wait_after_first_frame(
        monkeypatch, startup_timeout, first_frame, expected_wait):
    now, calls = [0.], []
    bot = JumpRopeBot(BotConfig(observe_only=True, startup_timeout=startup_timeout),
                      clock=lambda: now[0],
                      sleeper=lambda _: now.__setitem__(0, now[0]+1))

    class Capture:
        def __init__(self, _): pass
        def grab(self):
            calls.append(1)
            if first_frame and len(calls) == 1:
                return live_frame()
            raise controller.TemporaryCaptureOverlayError('launch banner')

    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123))
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(bot, 'tap_jump', lambda _: pytest.fail('overlay authorized input'))
    with pytest.raises(controller.TemporaryCaptureOverlayError, match='launch banner'):
        bot.run()
    # A successfully captured frame sleeps once; the following overlay must
    # stop immediately rather than granting another startup waiting window.
    assert now[0] == expected_wait + int(first_frame)
    assert len(calls) == (2 if first_frame else expected_wait+1)
    assert bot.stop_reason == 'error'
    assert bot.tap_count == 0


@pytest.mark.parametrize('outcome', ['fresh', 'timeout', 'stopped', 'focus_lost', 'gameplay'])
def test_static_loading_wait_is_bounded_and_never_reuses_pixels(monkeypatch, outcome):
    now, calls = [0.], []
    bot = JumpRopeBot(BotConfig(observe_only=True, wait_for_round=True,
                                startup_timeout=.25, result_postroll=0),
                      clock=lambda: now[0], sleeper=lambda t: now.__setitem__(0, now[0]+t),
                      stop_requested=lambda: bool(calls) and outcome == 'stopped')
    class Capture:
        def __init__(self, _): pass
        def grab(self):
            calls.append(1)
            now[0] += .1
            if outcome == 'gameplay' and len(calls) == 1:
                return live_frame()
            if outcome == 'fresh' and len(calls) == 2:
                bot.stop()
                return np.zeros_like(live_frame())
            raise controller.NoFreshFrameError('no new pixels')
    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123))
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow',
                        lambda: 456 if calls and outcome == 'focus_lost' else 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(bot, 'tap_jump', lambda _: pytest.fail('input without pixels'))
    bot.run()
    assert bot.stop_reason == {'fresh': 'stopped', 'timeout': 'startup_timeout',
                               'gameplay': 'startup_timeout'}.get(outcome, outcome)
    assert len(calls) == {'fresh': 2, 'timeout': 3, 'gameplay': 3}.get(outcome, 1)
    assert bot.input_times == []


def test_jump_position_is_derived_from_visible_button():
    x, y = RoundGate.jump_position(live_frame())
    assert x == pytest.approx(820/960, abs=.005)
    assert y == pytest.approx(425/540, abs=.005)
    assert RoundGate.jump_position(np.zeros((540, 960, 3), np.uint8)) is None


def test_loading_tip_with_hud_like_colors_does_not_seal_gameplay():
    from pathlib import Path
    frame = cv2.imread(str(Path(__file__).parent/'fixtures/loading-tip-false-hud.jpg'))
    assert frame is not None
    assert not RoundGate.gameplay_visible(frame)


@pytest.mark.parametrize('visible_rope', [False, True])
def test_initial_static_hud_wait_is_bounded_and_ends_after_rope_evidence(monkeypatch, visible_rope):
    now, calls = [0.], []
    bot = JumpRopeBot(BotConfig(observe_only=True, wait_for_round=True,
                                startup_timeout=10, result_postroll=0),
                      clock=lambda: now[0], sleeper=lambda t: now.__setitem__(0, now[0]+t))
    class Capture:
        def __init__(self, _): pass
        def grab(self):
            calls.append(1)
            now[0] += .1
            if len(calls) <= 3:
                return live_frame()
            raise controller.NoFreshFrameError('no new pixels')
    class Detector:
        position = RopePosition(0, .9 if visible_rope else 0, 0)
        last_score = 0
        def observe(self, _frame, _now): return False
    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123))
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller, 'VisualPassDetector', Detector)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(bot, 'tap_jump', lambda _: pytest.fail('input without pixels'))
    with pytest.raises(controller.NoFreshFrameError):
        bot.run()
    assert len(calls) == 4 if visible_rope else 30 <= len(calls) <= 32
    assert bot.tap_count == 0


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
    assert events == [False, True, False, False, False, False, False, False]


def test_blue_rope_triggers_before_old_late_threshold():
    detector = measured_detector([
        RopePosition(-.3, .8, 0), RopePosition(-.2, .8, 0),
        RopePosition(-.11, .8, 0), RopePosition(.055, .8, 0),
        RopePosition(.125, .8, 0),
    ])
    assert [detector.observe(None, i*.065) for i in range(5)] == [
        False, True, False, False, False,
    ]


def test_fast_blue_arc_does_not_wait_for_foot_zone():
    detector = measured_detector([
        RopePosition(-.44, .55, 0, 'blue', .16),
        RopePosition(-.37, .42, 0, 'blue', .06),
        RopePosition(-.105, .36, 0, 'blue', .04),
        RopePosition(-.02, .83, 0, 'blue', .2),
    ])
    assert [detector.observe(None, i*.065) for i in range(4)] == [
        False, False, True, False,
    ]


def test_blue_pass_requires_seen_far_retreat_before_another_jump():
    positions = [
        RopePosition(-.45, .8, 0), RopePosition(-.36, .8, 0),
        RopePosition(-.20, .8, 0),  # first real approach
        RopePosition(-.49, .8, 0), RopePosition(-.37, .8, 0),
        RopePosition(-.19, .8, 0),  # prop-induced arc snap: not another jump
        RopePosition(-.50, .8, 0), RopePosition(-.45, .8, 0),
        RopePosition(-.40, .8, 0),  # three visible far-rope frames
        RopePosition(-.29, .8, 0), RopePosition(-.20, .8, 0),
    ]
    detector = measured_detector(positions)
    assert [i for i in range(len(positions)) if detector.observe(None, i*.065)] == [2, 10]


def test_smooth_visible_retreat_rearms_even_when_far_arc_is_obscured():
    heights = [-.45, -.36, -.20, .08, .05, .02, -.03, -.10,
               -.18, -.28, -.33, -.24]
    detector = measured_detector([RopePosition(h, .7, 0) for h in heights])
    assert [i for i in range(len(heights)) if detector.observe(None, i*.065)] == [2, 11]


def test_prop_snap_after_exit_does_not_fake_a_new_blue_cycle():
    heights = [-.45, -.36, -.20, .08, .02, -.43, -.11, -.29, -.18]
    detector = measured_detector([RopePosition(h, .7, 0) for h in heights])
    assert [i for i in range(len(heights)) if detector.observe(None, i*.065)] == [2]


def test_shallow_gold_approach_can_arm_and_cross():
    detector = measured_detector([
        RopePosition(-.095, .6, 0, 'gold'),
        RopePosition(-.05, .6, 0, 'gold'),
        RopePosition(-.035, .8, 0, 'gold'),
        RopePosition(-.02, .8, 0, 'gold'),
        RopePosition(.03, .8, 0, 'gold'),
    ])
    assert [detector.observe(None, i*.065) for i in range(5)] == [
        False, False, False, True, False,
    ]


def test_gold_ground_rope_keeps_shallow_gate_through_color_flicker():
    positions = [
        RopePosition(.01, .89, 0, 'gold', .06),
        RopePosition(-.01, .84, 0, 'gold', .06),
        RopePosition(-.06, .61, 0, 'blue', .06),
        RopePosition(-.06, .49, 0, 'blue', .08),
        RopePosition(-.105, .54, 0, 'gold', .14),
        RopePosition(-.07, .34, 0, 'blue', .08),
        RopePosition(-.025, .58, 0, 'gold', .16),
    ]
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, False, False, False, True,
    ]


def test_short_occlusion_preserves_seen_approach_but_does_not_click_blind():
    positions = ([RopePosition(-.3, .7, 0), RopePosition(-.4, .7, 0)]
                 + [RopePosition(0, .1, 0)] * 4
                 + [RopePosition(-.08, .7, 0), RopePosition(-.03, .7, 0),
                    RopePosition(.02, .7, 0)])
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, False, False, False, False, False, True,
    ]


def test_blue_rope_triggers_on_confident_reappearance_after_short_occlusion():
    positions = ([RopePosition(-.42, .55, 0, 'blue', .2),
                  RopePosition(-.45, .5, 0, 'blue', .2)]
                 + [RopePosition(-.11, .2, 0, 'blue', .1)] * 4
                 + [RopePosition(-.105, .42, 0, 'blue', .14),
                    RopePosition(-.02, .6, 0, 'blue', .4)])
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, False, False, False, True, False,
    ]


def test_blue_rope_can_reappear_after_five_hidden_frames():
    positions = ([RopePosition(-.42, .55, 0, 'blue', .2),
                  RopePosition(-.45, .5, 0, 'blue', .2)]
                 + [RopePosition(-.11, .2, 0, 'blue', .08)] * 5
                 + [RopePosition(-.075, .46, 0, 'blue', .27)])
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, False, False, False, False, True,
    ]


def test_one_frame_edge_occlusion_does_not_delay_fast_blue_arc():
    detector = measured_detector([
        RopePosition(-.44, .55, 0, 'blue', .16),
        RopePosition(-.42, .40, 0, 'blue', .10),
        RopePosition(-.42, .345, 0, 'blue', .06),
        RopePosition(-.20, .39, 0, 'blue', .14),
        RopePosition(.04, .76, 0, 'blue', .32),
    ])
    assert [detector.observe(None, i*.065) for i in range(5)] == [
        False, False, False, True, False,
    ]


def test_partial_rope_reappearing_after_four_hidden_frames_can_trigger():
    positions = ([RopePosition(-.42, .55, 0, 'blue', .2),
                  RopePosition(-.45, .5, 0, 'blue', .2)]
                 + [RopePosition(-.11, .2, 0, 'blue', .08)] * 4
                 + [RopePosition(-.105, .31, 0, 'blue', .14)])
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, False, False, False, True,
    ]


def test_blue_reappearance_tolerates_weak_but_present_line_contrast():
    positions = ([RopePosition(-.42, .55, 0, 'blue', .2),
                  RopePosition(-.45, .5, 0, 'blue', .2)]
                 + [RopePosition(-.11, .2, 0, 'blue', .08)] * 4
                 + [RopePosition(-.055, .41, 0, 'blue', .068)])
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, False, False, False, True,
    ]


def test_pink_rope_reappears_before_foot_crossing():
    positions = ([RopePosition(-.42, .55, 0, 'pink', .2),
                  RopePosition(-.45, .5, 0, 'pink', .2)]
                 + [RopePosition(-.28, .27, 0, 'pink', .07)] * 3
                 + [RopePosition(-.165, .38, 0, 'pink', .09)])
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, False, False, True,
    ]


def test_two_visible_rope_fragments_can_trigger_before_full_reappearance():
    positions = ([RopePosition(-.42, .55, 0, 'blue', .2),
                  RopePosition(-.45, .5, 0, 'blue', .2),
                  RopePosition(-.31, .27, 0, 'blue', .15),
                  RopePosition(-.16, .29, 0, 'gold', .15),
                  RopePosition(-.075, .39, 0, 'blue', .21)])
    detector = measured_detector(positions)
    assert [detector.observe(None, i*.065) for i in range(len(positions))] == [
        False, False, False, True, False,
    ]


def test_occlusion_reappearance_requires_line_contrast():
    positions = ([RopePosition(-.42, .55, 0, 'blue', .2),
                  RopePosition(-.45, .5, 0, 'blue', .2)]
                 + [RopePosition(-.11, .2, 0, 'blue', .1)] * 4
                 + [RopePosition(-.105, .42, 0, 'blue', .04)])
    detector = measured_detector(positions)
    assert not any(detector.observe(None, i*.065) for i in range(len(positions)))


def test_long_occlusion_does_not_trigger_on_reappearance():
    positions = ([RopePosition(-.3, .7, 0), RopePosition(-.4, .7, 0)]
                 + [RopePosition(0, .1, 0)] * 6
                 + [RopePosition(-.08, .7, 0), RopePosition(.02, .7, 0)])
    detector = measured_detector(positions)
    assert not any(detector.observe(None, i*.065) for i in range(len(positions)))


def test_weak_floor_outlier_does_not_invent_a_trough_or_rebound():
    heights = [.13, .14, .135, .115, .105, .06, .105]
    coverages = [.9, .9, .9, .6, .5, .15, .6]
    detector = measured_detector([
        RopePosition(h, c, 0, 'gold') for h, c in zip(heights, coverages)
    ])
    assert [detector.observe(None, i*.065) for i in range(len(heights))] == [
        False, False, False, False, False, False, False,
    ]


def test_next_gold_swing_can_fire_on_well_seen_descent():
    detector = measured_detector([
        RopePosition(-.09, .8, 0, 'gold'),
        RopePosition(-.05, .8, 0, 'gold'),
        RopePosition(-.02, .8, 0, 'gold'),
        RopePosition(.14, .78, 0, 'gold'),
        RopePosition(.14, .55, 0, 'gold'),
        RopePosition(.12, .8, 0, 'gold'),
        RopePosition(.11, .98, 0, 'gold'),
        RopePosition(.09, .98, 0, 'blue'),
    ])
    assert [detector.observe(None, i*.065) for i in range(8)] == [
        False, False, True, False, False, False, False, True,
    ]


def test_floor_trough_below_confidence_threshold_cannot_arm_a_rebound():
    # Old logic accepted the weak .05 fit as a trough. The new night-stage
    # recording shows that an obscuring prop can generate exactly that dip.
    heights = [.115, .12, .14, .14, .135, .13, .11, .085, .05, .10, .11]
    coverages = [.99, .93, .85, .55, .71, .65, .55, .28, .14, .31, .51]
    detector = measured_detector([
        RopePosition(h, c, 0, 'gold') for h, c in zip(heights, coverages)
    ])
    assert [detector.observe(None, i*.065) for i in range(len(heights))] == [
        False, False, False, False, False, False, False, False, False,
        False, False,
    ]


def test_gold_floor_occlusion_never_clicks_without_reappearance():
    positions = ([RopePosition(h, .8, 0, 'gold')
                  for h in [.13, .14, .13, .12, .11]]
                 + [RopePosition(-.1, .15, 0, 'blue')] * 5)
    detector = measured_detector(positions)
    assert not any(detector.observe(None, i*.065) for i in range(len(positions)))


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
    assert len(bot.input_times) == 1


def test_prearmed_round_waits_for_play_and_never_restarts(monkeypatch, tmp_path):
    menu = np.zeros_like(live_frame())
    live = live_frame()
    frames = iter([menu, menu, live, live, live, live, live, menu, live, live])

    class Capture:
        def __init__(self, _):
            pass

        def grab(self):
            return next(frames)

    class Detector:
        last_score = .8
        position = RopePosition(.1, .8, 0)

        def observe(self, frame, now):
            return True

    now = [0.]
    def sleep(seconds):
        now[0] += seconds

    path = tmp_path / 'one-round.mp4'
    bot = JumpRopeBot(BotConfig(record_path=path, wait_for_round=True,
                                result_postroll=0), clock=lambda: now[0], sleeper=sleep)
    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123) or 123)
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller, 'VisualPassDetector', Detector)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(controller.win32api, 'mouse_event', lambda *args: None)
    taps = []
    def tap(_):
        taps.append(now[0])
        bot.last_tap_at = now[0]
        bot.input_times.append(now[0])
        return True
    monkeypatch.setattr(bot, 'tap_jump', tap)

    bot.run()

    import json
    import gzip
    directory = path.with_suffix('')
    evidence = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['result']
    with gzip.open(directory/'frames.jsonl.gz', 'rt', encoding='utf-8') as stream:
        evidence['frames'] = [json.loads(line) for line in stream]
    assert bot.stop_reason == 'round_finished'
    assert len(taps) == 1
    assert evidence['round_started_t'] is not None
    assert all(not entry['clicked'] for entry in evidence['frames'] if entry['phase'] == 'waiting')
    assert all(not entry['clicked'] for entry in evidence['frames'] if entry['phase'] == 'result')
    assert sum(entry['input_elapsed'] is not None for entry in evidence['frames']) == 1
    result_t = min(entry['t'] for entry in evidence['frames'] if entry['phase'] == 'result')
    assert max(evidence['input_times']) < result_t


def test_prearmed_round_times_out_on_menu_without_input(monkeypatch, tmp_path):
    class Capture:
        def __init__(self, _):
            pass

        def grab(self):
            return np.zeros_like(live_frame())

    now = [0.]
    bot = JumpRopeBot(BotConfig(record_path=tmp_path / 'menu.mp4', observe_only=True,
                                wait_for_round=True,
                                startup_timeout=.1, result_postroll=0),
                      clock=lambda: now[0], sleeper=lambda seconds: now.__setitem__(0, now[0]+seconds))
    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123) or 123)
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(controller.win32api, 'mouse_event',
                        lambda *args: pytest.fail('observe mode sent a mouse event'))

    bot.run()

    assert bot.stop_reason == 'startup_timeout'
    assert bot.tap_count == 0


@pytest.mark.parametrize('interruption', ['stopped', 'focus_lost'])
def test_stop_during_result_recording_tail_cancels_batch_restart(monkeypatch, tmp_path, interruption):
    state = {'captures': 0, 'ended': False}

    class Capture:
        def __init__(self, _):
            pass

        def grab(self):
            state['captures'] += 1
            if state['captures'] <= 3:
                return live_frame()
            state['ended'] = True
            return np.zeros_like(live_frame())

    now = [0.]
    bot = JumpRopeBot(BotConfig(observe_only=True, result_postroll=3,
                                record_path=tmp_path / 'tail.mp4'),
                      clock=lambda: now[0], sleeper=lambda t: now.__setitem__(0, now[0]+t),
                      stop_requested=lambda: state['ended'] and interruption == 'stopped')
    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123) or 123)
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow',
                        lambda: 456 if state['ended'] and interruption == 'focus_lost' else 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(controller.win32api, 'mouse_event', lambda *args: pytest.fail('unexpected input'))
    bot.run()
    assert bot.stop_reason == interruption
    assert state['captures'] == 4
    assert bot.input_times == []
