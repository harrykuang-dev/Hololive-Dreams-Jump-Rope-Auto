from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from rope_track import RopePosition, SegmentedRopeTracker, VisualPassDetector


def arc_frame(sag, left=.55, right=.43, obstacle=False):
    frame = np.full((540, 960, 3), (45, 100, 50), np.uint8)
    t = np.linspace(0, 1, 400)
    xs = (.235+.605*t)*960
    ys = (left+(right-left)*t+sag*4*t*(1-t))*540
    points = np.stack([xs, ys], axis=1).astype(np.int32)
    cv2.polylines(frame, [points], False, (245, 240, 240), 3)
    if obstacle:
        cv2.circle(frame, (520, 180), 60, (255, 220, 150), -1)
        cv2.rectangle(frame, (500, 130), (540, 230), (250, 250, 250), -1)
    return frame


def test_raised_rope_hands_and_central_occlusion_do_not_move_fit_to_prop():
    tracker = SegmentedRopeTracker()
    tracker.locate(arc_frame(-.36, obstacle=True))
    pos = tracker.locate(arc_frame(-.23, obstacle=True))
    player_t = (.565-.235)/.605
    expected = (.55+(.43-.55)*player_t-.23*4*player_t*(1-player_t)
                -(.648-.238*player_t))
    assert pos.coverage >= .4
    assert pos.sag+pos.offset == pytest.approx(expected, abs=.025)


def test_recorded_floor_occlusion_does_not_invent_deep_plateau_dip():
    root = Path(__file__).parent / 'fixtures' / 'rope' / 'occluded-floor-v9'
    rows = json.loads((root/'sequence.json').read_text())['frames']
    tracker = SegmentedRopeTracker()
    for row in rows:
        tracker.capture_time = row['t']
        pos = tracker.locate(cv2.imread(str(root/row['file'])))
        if row['frame'] == 2232:
            # Two visible side sections support a still-high shallow arc.
            # Unregularized fitting snaps to ~.047 on the moving bowl.
            assert pos.sag == pytest.approx(.13, abs=.025)
            assert pos.coverage >= .45  # Current pixels, not invented confidence.


def test_recorded_bowls_keep_visible_retreat_instead_of_near_ground_fit():
    root = Path(__file__).parent / 'fixtures' / 'rope' / 'occluded-retreat-v10'
    rows = json.loads((root/'sequence.json').read_text())['frames']
    tracker = SegmentedRopeTracker()
    baseline = SegmentedRopeTracker()
    baseline.local_refinement = False
    baseline.appearance_consistency = False
    for row in rows:
        frame = cv2.imread(str(root/row['file']))
        tracker.capture_time = baseline.capture_time = row['t']
        pos, old = tracker.locate(frame), baseline.locate(frame)
    # Frame 2752: visible left/right rope retreats above the player while
    # the center is covered by bowls. v10 short replay picked a ground fit.
    assert old.sag > -.1
    assert pos.sag == pytest.approx(-.28, abs=.035)
    assert pos.coverage >= .45


def test_stale_rope_palette_cannot_manufacture_pixels():
    tracker = SegmentedRopeTracker()
    tracker.rope_palette = np.array([115., 150., 150.])
    tracker.palette_time = 0
    frame = np.full((540, 960, 3), 60, np.uint8)
    tracker.capture_time = 1
    tracker.locate(frame)
    tracker.capture_time = 1.03
    pos = tracker.locate(frame)
    assert pos.coverage == 0
    assert not tracker.appearance_prior_used


def test_strong_new_rope_color_is_not_locked_to_previous_palette():
    tracker = SegmentedRopeTracker()
    tracker.rope_palette = np.array([115., 150., 150.])
    tracker.palette_time = 0
    for i, sag in enumerate([-.4, -.25]):
        frame = arc_frame(sag)
        frame[frame[:, :, 0] == 245] = (30, 210, 230)
        tracker.capture_time = i*.03
        pos = tracker.locate(frame)
    assert pos.color == 'gold'
    assert pos.coverage >= .7
    assert not tracker.appearance_prior_used


@pytest.mark.parametrize('name,height', [
    ('raised-hand', -.33), ('bowls-at-apex', -.45),
    ('occluded-approach', -.19), ('warm-rope', -.14),
    ('night-violet', -.32),
])
def test_recorded_rope_stays_on_visually_labelled_arc(name, height):
    # These are independently inspected central rope heights. Full source
    # video names/frame indices are in fixtures/rope/README.md.
    root = Path(__file__).parent / 'fixtures' / 'rope'
    tracker = SegmentedRopeTracker()
    for suffix in ('before', 'current'):
        frame = cv2.imread(str(root / f'{name}-{suffix}.jpg'))
        assert frame is not None
        pos = tracker.locate(frame)
    assert pos.coverage >= .35
    assert pos.sag+pos.offset == pytest.approx(height, abs=.045)


def test_warm_color_on_overhead_arc_does_not_select_floor_timing():
    detector = VisualPassDetector()
    positions = iter([RopePosition(h, .8, 0., 'gold') for h in [-.44, -.36, -.20, -.10]])
    detector.tracker.locate = lambda _: next(positions)
    assert [detector.observe(None, i*.065) for i in range(4)] == [False, False, True, False]
    assert not detector.gold_mode


def test_a_full_overhead_arc_ends_floor_mode_even_if_it_looks_gold():
    detector = VisualPassDetector()
    detector.gold_mode = True
    positions = iter([RopePosition(h, .8, 0., 'gold') for h in [-.44, -.36, -.20]])
    detector.tracker.locate = lambda _: next(positions)
    assert [detector.observe(None, i*.065) for i in range(3)] == [False, False, True]
    assert not detector.gold_mode


def test_fragment_event_also_requires_retreat_before_the_next_event():
    positions = ([RopePosition(-.42, .6, 0., 'blue', .2)]*2
                 + [RopePosition(-.1, .15, 0., 'blue', .05)]*4
                 + [RopePosition(-.1, .31, 0., 'blue', .14),
                    RopePosition(-.45, .8, 0.), RopePosition(-.36, .8, 0.),
                    RopePosition(-.20, .8, 0.)])
    detector = VisualPassDetector()
    iterator = iter(positions)
    detector.tracker.locate = lambda _: next(iterator)
    assert [i for i in range(len(positions)) if detector.observe(None, i*.065)] == [6]
