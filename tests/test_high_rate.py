import cv2
import json
import numpy as np
import pytest
from pathlib import Path

from jump_rope_bot import BotConfig
from rope_track import RopePosition, SegmentedRopeTracker, VisualPassDetector
from tests.test_rope_geometry import arc_frame


def feed(detector, height, now, coverage=.9, color='blue'):
    detector.tracker.locate = lambda _: RopePosition(height, coverage, 0, color, .6)
    return detector.observe(None, now)


def test_high_rate_context_does_not_treat_short_prop_flash_as_six_samples():
    detector = VisualPassDetector()
    for i, h in enumerate([.06, .08, .10, .12, .14, .14]):
        assert not feed(detector, h, i/60)
    assert not detector.gold_mode


def test_high_rate_two_frame_far_snap_cannot_rearm():
    detector = VisualPassDetector()
    assert not feed(detector, -.45, 0)
    assert not feed(detector, -.36, .06)
    assert feed(detector, -.2, .12)
    for i, h in enumerate([-.45, -.43, -.4, -.37, -.2], 1):
        assert not feed(detector, h, .12+i/120)


def test_high_rate_occlusion_budget_is_not_exhausted_after_80ms():
    detector = VisualPassDetector()
    feed(detector, -.45, 0)
    feed(detector, -.4, .06)
    for i in range(1, 7):
        assert not feed(detector, -.35, .06+i/60, coverage=.1)
    assert feed(detector, -.2, .18)


def test_duplicate_pixels_do_not_increment_detector_evidence():
    detector = VisualPassDetector()
    frame = arc_frame(-.4)
    detector.observe(frame, 0)
    for i in range(1, 8):
        assert not detector.observe(frame, i/60)
        assert detector.last_reason == 'duplicate_frame'
    assert not detector.armed


def test_global_scene_cut_requires_reacquisition_without_input():
    detector = VisualPassDetector()
    dark = np.full((540, 960, 3), 30, np.uint8)
    bright = np.full_like(dark, 150)
    detector.observe(dark, 0)
    detector.armed = True
    assert not detector.observe(bright, .06)
    assert detector.last_reason == 'scene_cut_reacquire'
    assert not detector.armed
    assert detector.blue_rearm_needed
    assert detector.tracker.coefficients is None


def test_three_partial_floor_peak_observations_survive_occlusion():
    detector = VisualPassDetector()
    heights = [.06, .10, .132, .134, .129, .113, .131, .110]
    events = [feed(detector, h, i*.06, coverage=.40 if 2 <= i <= 4 else .9,
                   color='gold') for i, h in enumerate(heights)]
    assert events == [False]*7 + [True]


@pytest.mark.parametrize('fps', [15, 30, 60])
def test_frame_budget_configuration(fps):
    BotConfig(target_fps=fps).validate()


@pytest.mark.parametrize('fps', [0, 61, float('nan')])
def test_invalid_capture_rate_rejected(fps):
    with pytest.raises(ValueError):
        BotConfig(target_fps=fps).validate()


@pytest.mark.parametrize('fps', [15, 30, 60])
def test_same_visible_two_swing_trajectory_has_two_events_at_each_rate(fps):
    detector = VisualPassDetector()
    events = []
    for t in np.arange(0, 1.0, 1/fps):
        h = float(np.interp(t, [0, .2, .3, .55, .8, .95], [-.45, .08, -.1, -.45, .08, -.3]))
        if feed(detector, h, float(t)):
            events.append(t)
    assert len(events) == 2


def test_dense_gold_hue_during_normal_arc_cannot_create_floor_extra_jump():
    detector = VisualPassDetector()
    events = []
    for i in range(45):
        t = i/60
        h = float(np.interp(t, [0, .15, .25, .34, .45, .60, .73],
                           [-.45, -.32, -.08, .13, .06, -.18, -.43]))
        if feed(detector, h, t, color='gold'):
            events.append(t)
    assert len(events) == 1
    assert not detector.gold_mode


def test_native_sixty_fps_inspected_prop_and_gold_windows():
    source = Path(__file__).parent / 'fixtures' / 'gate' / 'native60-v9-raw.json'
    detector = VisualPassDetector()
    events = []
    for t, h, c, color, contrast in json.loads(source.read_text())['measurements']:
        detector.tracker.locate = lambda _, pos=RopePosition(h, c, 0, color, contrast): pos
        if detector.observe(None, t):
            events.append(t)
    # Reviewed native frames: reject the gold near-half duplicate and the
    # prop jumps at 79.084 and 81.567, retain the actual visible approaches.
    for start, end, expected in [(35.5, 36.5, 35.7), (79.0, 79.5, 79.284),
                                 (81.5, 82.05, 81.951)]:
        assert [t for t in events if start <= t <= end] == [expected]


def test_partial_single_frame_snap_cannot_change_mode_or_trigger():
    detector = VisualPassDetector()
    feed(detector, -.45, 0)
    feed(detector, -.38, .06)
    assert not feed(detector, -.1, .076, coverage=.46)
    assert detector.last_reason == 'partial_geometry_snap'
    assert detector.position.sag == -.38
    assert feed(detector, -.26, .092, coverage=.85)


def test_dense_two_weak_fragments_cannot_authorize_an_early_jump():
    detector = VisualPassDetector()
    assert not feed(detector, -.45, 0)
    assert not feed(detector, -.42, .06)
    assert not feed(detector, -.16, .076, coverage=.27)
    assert not feed(detector, -.075, .092, coverage=.29)
    assert feed(detector, -.15, .12, coverage=.8)
