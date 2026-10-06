"""Archived screenshot-only surface filter, not application policy."""
import cv2
import numpy as np
import pytest
from experiments.rope_track_v23 import SegmentedRopeTracker
from test_rope_geometry import arc_frame


def test_wide_colored_moving_rim_cannot_become_a_rope():
    current = SegmentedRopeTracker()
    previous = SegmentedRopeTracker()
    previous.thin_line_filter = False
    for i, sag in enumerate((-.3, -.2)):
        frame = np.full((540, 960, 3), (45, 100, 50), np.uint8)
        t = np.linspace(0, 1, 400)
        points = np.stack([(.235+.605*t)*960,
                           (.55+(.43-.55)*t+sag*4*t*(1-t))*540], axis=1).astype(np.int32)
        cv2.polylines(frame, [points], False, (240, 150, 75), 13)
        current.capture_time = previous.capture_time = i*.05
        pos, old = current.locate(frame), previous.locate(frame)
    assert old.coverage > .8  # The prior detector treats this surface as a rope.
    assert pos.coverage == 0
    assert current.surface_rejected_fraction > .8


def test_white_glowing_rope_is_not_discarded_by_surface_filter():
    tracker = SegmentedRopeTracker()
    for i, sag in enumerate((-.3, -.2)):
        frame = arc_frame(sag)
        # A broad neutral glow must retain measured rope support.
        frame = cv2.dilate(frame, np.ones((9, 1), np.uint8))
        tracker.capture_time = i*.05
        pos = tracker.locate(frame)
    assert pos.coverage >= .7
    player_t = (.565-.235)/.605
    expected = .55+(.43-.55)*player_t-.2*4*player_t*(1-player_t)-(.648-.238*player_t)
    assert pos.sag == pytest.approx(expected, abs=.025)
