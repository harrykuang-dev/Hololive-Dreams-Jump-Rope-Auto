"""Visual crossing settings without running the game or sending input."""

import numpy as np
import pytest

from batch_session import SessionConfig
from jump_detector import VisualPassDetector
from jump_rope_bot import BotConfig
from rope_geometry import RopePosition
from timing_control import (DEFAULT_TIMING_POSITION, detector_for_timing,
                            threshold_for_position)


def observed_events(step, *, bands=(.6,)*5):
    heights = (-.5, -.45, -.4, -.36, -.3, -.26)
    detector = detector_for_timing(step)()
    detector.tracker.segment_support = list(bands)
    samples = iter(RopePosition(height, .8, 0, 'blue', .2) for height in heights)
    detector.tracker.locate = lambda _frame: next(samples)
    frame = np.zeros((540, 960, 3), np.uint8)
    return [(detector.observe(frame, index*.065), detector.last_reason)
            for index in range(len(heights))]


def test_centre_is_early37_and_rightmost_is_release_detector():
    assert DEFAULT_TIMING_POSITION == .5
    assert threshold_for_position(.5) == -.37
    assert threshold_for_position(0) == -.40
    assert threshold_for_position(1) == -.28
    assert threshold_for_position(.25) == -.385
    assert threshold_for_position(.75) == -.325
    assert detector_for_timing(1) is VisualPassDetector
    assert BotConfig().timing_position == SessionConfig().timing_position == .5


@pytest.mark.parametrize('position', [True, -1, 1.1, float('nan'), float('inf'), '0.5'])
def test_invalid_slider_position_rejected(position):
    with pytest.raises(ValueError):
        BotConfig(timing_position=position).validate()
    with pytest.raises(ValueError):
        SessionConfig(timing_position=position).validate()


def test_slider_moves_the_same_visible_crossing_without_duplicate_input():
    earlier = observed_events(0)
    default = observed_events(.5)
    later = observed_events(.75)
    release = observed_events(1)
    assert [index for index, event in enumerate(earlier) if event[0]] == [2]
    assert [index for index, event in enumerate(default) if event[0]] == [3]
    assert [index for index, event in enumerate(later) if event[0]] == [4]
    assert [index for index, event in enumerate(release) if event[0]] == [5]
    assert default[3][1] == 'early_overhead_approach'
    assert release[5][1] == 'overhead_approach'


def test_early_crossing_requires_side_support():
    weak = observed_events(.5, bands=(.1, .1, .6, .6, .6))
    assert not weak[3][0]


def test_subtick_positions_are_not_rounded_to_reference_marks():
    assert threshold_for_position(.51) != threshold_for_position(.50)
    assert threshold_for_position(.49) != threshold_for_position(.50)
