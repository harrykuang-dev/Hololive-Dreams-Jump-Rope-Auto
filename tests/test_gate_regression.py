"""Timing contracts for inspected failures, NOT assertions of game success."""
import json
from pathlib import Path

import pytest

from rope_track import RopePosition, VisualPassDetector


def replay(positions):
    detector = VisualPassDetector()
    events = []
    for t, h, c, color, contrast in positions:
        detector.tracker.locate = lambda _, pos=RopePosition(h, c, 0, color, contrast): pos
        if detector.observe(None, t):
            events.append(t)
    return events


def test_v15_dense_floor_wobble_keeps_the_later_return():
    source = Path(__file__).parent / 'fixtures' / 'gate' / 'v15-round-3.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    # The .009 rise in one ~22 ms capture was a plateau fitting wobble.
    # Inspecting the first loss shows the later second crest and return.
    assert not any(70.90 <= t <= 71.0 for t in events)
    assert [t for t in events if 71.20 <= t <= 71.35] == [71.237]


def test_v15_one_frame_weak_fragment_keeps_the_visible_reappearance():
    source = Path(__file__).parent / 'fixtures' / 'gate' / 'v15-round-3.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    # Near the third loss, two weak prop fits 16 ms apart borrow the far
    # rope's arming evidence. Wait for the actual visible reappearance.
    assert not any(105.45 <= t <= 105.55 for t in events)
    assert [t for t in events if 105.60 <= t <= 105.80] == [105.6222]


def test_v15_partial_gold_crossing_survives_one_hidden_capture():
    source = Path(__file__).parent / 'fixtures' / 'gate' / 'v15-round-3.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    assert [t for t in events if 86.25 <= t <= 86.50] == [86.3536]


def test_v16_lone_partial_far_prop_cannot_erase_the_floor_return():
    source = Path(__file__).parent / 'fixtures' / 'gate' / 'v16-round-1.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    # Strong visible floor descent was ignored until .054 because a single
    # .385-coverage prop fit had switched mode to overhead.
    assert [t for t in events if 84.70 <= t <= 84.95] == [84.8286]


def test_v9_occluded_floor_dip_does_not_consume_the_later_return():
    source = Path(__file__).parent / 'fixtures' / 'gate' / 'v9-round-1.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    # Raw live measurements, independent of compressed-pixel fitting:
    # the bowl-rim dips at 72.9075/83.9617 must not create early triggers.
    assert not any(72.9 <= t <= 73.05 for t in events)
    assert not any(83.94 <= t <= 84.05 for t in events)
    assert len([t for t in events if 73.2 <= t <= 73.6]) == 1
    assert len([t for t in events if 84.15 <= t <= 84.4]) == 1


@pytest.mark.parametrize('round_number,rejected,retained', [
    (3, [(85.7, 85.9), (94.85, 95.05), (101.7, 101.9)],
     [(86.1, 86.3), (94.4, 94.6), (102.1, 102.3)]),
    (4, [(71.8, 72.0)], [(72.2, 72.4)]),
])
def test_v10_short_retreat_then_prop_fit_cannot_consume_next_jump(round_number, rejected, retained):
    source = Path(__file__).parent / 'fixtures' / 'gate' / f'v10-round-{round_number}.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    for lo, hi in rejected:
        assert not any(lo <= t <= hi for t in events)
    for lo, hi in retained:
        assert len([t for t in events if lo <= t <= hi]) == 1


def test_two_weak_fragments_cannot_teleport_into_an_approach():
    positions = [(-.45, .8), (-.40, .8), (-.36, .28), (-.12, .31), (-.26, .8)]
    assert replay([(i*.034, h, c, 'blue', .4)
                   for i, (h, c) in enumerate(positions)]) == [.136]


def test_v11_full_sequence_retains_occluded_crest_and_short_visible_apex():
    source = Path(__file__).parent / 'fixtures' / 'gate' / 'v11-round-4.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    # Inspected MP4 losses at 100.064/118.091. A .119 crest was below the
    # old .12 peak cutoff; three fresh far captures were sparsely sampled.
    # Full sequence, without resetting the state before either failure.
    assert [t for t in events if 99.75 <= t <= 100.0] == [99.8547]
    assert [t for t in events if 117.70 <= t <= 118.0] == [117.8074]


def test_dense_far_flash_has_insufficient_observed_duration_to_rearm():
    positions = [(0, -.45, .8), (.06, -.36, .8), (.12, -.2, .8),
                 (.13, -.43, .33), (.14, -.44, .46), (.15, -.45, .535),
                 (.16, -.25, .8), (.17, -.10, .8)]
    assert replay([(t, h, c, 'blue', .4) for t, h, c in positions]) == [.12]


@pytest.mark.parametrize('round_number,windows', [
    (1, [(47.75, 47.95), (68.70, 68.90), (82.45, 82.65)]),
    (2, [(59.9, 60.15), (73.65, 73.85), (88.40, 88.65)]),
    (3, [(59.0, 59.18), (69.55, 69.72), (87.85, 88.05)]),
])
def test_inspected_misses_have_one_visible_candidate_in_reviewed_window(round_number, windows):
    source = Path(__file__).parent / 'fixtures' / 'gate' / f'v5-round-{round_number}.json'
    data = json.loads(source.read_text(encoding='utf-8'))
    events = replay(data['measurements'])
    for start, end in windows:
        assert len([t for t in events if start <= t <= end]) == 1
    if round_number == 2:
        # The former 59.746 event was on a small plateau dip, not the later
        # approach. It previously fired again only 0.35 seconds afterwards.
        assert not any(59.5 <= t < 59.9 for t in events)


def test_two_far_prop_snaps_do_not_rearm_after_a_pass():
    positions = [(-.44, .8), (-.36, .8), (-.2, .8),
                 (-.43, .8), (-.4, .8), (-.15, .8), (0., .8)]
    assert replay([(i*.06, h, c, 'gold', .4) for i, (h, c) in enumerate(positions)]) == [.12]


def test_floor_descent_latches_even_if_peak_reappears():
    heights = [-.09, -.05, -.02, .14, .14, .12, .10,
               .14, .14, .12, .09, .07, .03]
    # The first dip is not the return pass; fire after its observed rebound.
    assert replay([(i*.06, h, .9, 'gold', .5) for i, h in enumerate(heights)]) == [.12, .54]


@pytest.mark.parametrize('round_number,window', [
    (1, (63.90, 64.05)), (2, (70.3, 70.5)), (3, (96.48, 96.57)),
    (4, (90.30, 90.45)), (5, (54.75, 54.9)),
    (6, (94.3, 94.5)), (7, (90.45, 90.6)),
])
def test_v6_recorded_targeted_failure_windows(round_number, window):
    source = Path(__file__).parent / 'fixtures' / 'gate' / f'v6-round-{round_number}.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    assert len([t for t in events if window[0] <= t <= window[1]]) == 1
    if round_number == 2:
        assert not any(70.0 < t < 70.3 for t in events)  # first plateau dip
    if round_number == 6:
        assert not any(94.1 < t < 94.3 for t in events)  # weak false trough


def test_blue_floor_trajectory_not_color_establishes_mode():
    heights = [.06, .08, .10, .12, .14, .14, .12, .11, .13, .12, .09]
    detector = VisualPassDetector()
    events = []
    for i, h in enumerate(heights):
        detector.tracker.locate = lambda _, h=h: RopePosition(h, .95, 0, 'blue', .8)
        if detector.observe(None, i*.06):
            events.append(i)
    assert detector.gold_mode
    assert len(events) == 1


def test_static_blue_line_cannot_establish_floor_mode_or_fire():
    detector = VisualPassDetector()
    detector.tracker.locate = lambda _: RopePosition(.1, .95, 0, 'blue', .8)
    assert not any(detector.observe(None, i*.06) for i in range(40))
    assert not detector.gold_mode


def test_blue_floor_mode_keeps_peak_seen_before_mode_confirmation():
    detector = VisualPassDetector()
    heights = [.06, .10, .14, .135, .115, .11]
    for i, h in enumerate(heights):
        detector.tracker.locate = lambda _, h=h: RopePosition(h, .95, 0, 'blue', .8)
        assert not detector.observe(None, i*.06)
    assert detector.gold_mode
    assert detector.gold_peak
    assert detector.gold_peak_height == .14
    events = []
    for i, h in enumerate([.10, .115, .105], start=6):
        detector.tracker.locate = lambda _, h=h: RopePosition(h, .95, 0, 'blue', .8)
        events.append(detector.observe(None, i*.06))
    assert events == [False, False, True]


def test_floor_rebound_back_near_first_peak_is_not_discarded():
    # v7 recorded a .14 peak, .115 dip, then a .132 rebound. The rebound
    # was outside the old peak-minus-.015 zone, so the return was late.
    heights = [.06, .10, .14, .14, .13, .115, .132, .131, .112]
    events = replay([(i*.06, h, .95, 'gold', .8) for i, h in enumerate(heights)])
    assert events == [.48]


def test_blue_far_floor_mode_arms_from_existing_observations():
    # No extra far frame is available once six shallow samples confirm mode.
    heights = [-.05, -.075, -.10, -.11, -.09, -.065, -.025, .005]
    events = replay([(i*.06, h, .95, 'blue', .8) for i, h in enumerate(heights)])
    assert events == [.36]


@pytest.mark.parametrize('round_number,windows,count', [
    (1, [(77.20, 77.30)], 61),
    (2, [(57.55, 57.63), (81.10, 81.16)], 52),
    (3, [(71.01, 71.09)], 59),
    # v9 retains strong overhead evidence: removes the 67.4722 prop snap
    # during the already-counted 37th swing, without losing these windows.
    (4, [(76.23, 76.31), (90.23, 90.31)], 62),
    (5, [(77.60, 77.69), (102.65, 102.73)], 70),
    (6, [(81.92, 82.00), (97.86, 97.93)], 65),
    (7, [(36.37, 36.45), (57.87, 57.96), (72.24, 72.32)], 39),
])
def test_v7_full_sequences_keep_rebound_and_mode_entry_evidence(round_number, windows, count):
    source = Path(__file__).parent / 'fixtures' / 'gate' / f'v7-round-{round_number}.json'
    events = replay(json.loads(source.read_text(encoding='utf-8'))['measurements'])
    assert len(events) == count  # Regression count, never a game score.
    if round_number == 4:
        assert not any(67.35 <= t <= 67.55 for t in events)
    for start, end in windows:
        assert len([t for t in events if start <= t <= end]) == 1
