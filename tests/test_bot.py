import pytest
import cv2
import numpy as np

from jump_rope_bot import BotConfig, JumpRopeBot
from vision import RopeDetector, RopeTimingEstimator


def test_default_config_is_valid():
    BotConfig().validate()


@pytest.mark.parametrize("interval", [0, 0.01, 2.001])
def test_invalid_interval(interval):
    with pytest.raises(ValueError):
        BotConfig(tap_interval=interval).validate()


def test_key_down_must_be_shorter_than_interval():
    with pytest.raises(ValueError):
        BotConfig(tap_interval=0.04, key_down_time=0.04).validate()


def test_vision_is_the_default_strategy():
    assert BotConfig().strategy == "vision"


def test_rope_detector_emits_one_event_for_a_moving_rope_line():
    detector = RopeDetector()
    blank = np.zeros((500, 700, 3), dtype=np.uint8)
    rope = blank.copy()
    cv2.line(rope, (200, 350), (540, 350), (175, 138, 104), 5)
    assert detector.observe(blank, now=0.0) is False
    assert detector.observe(rope, now=1.0) is True
    # The same movement cannot create a second jump inside the safety gap.
    assert detector.observe(blank, now=1.1) is False


def test_timing_estimator_calibrates_from_visual_events_then_bridges_occlusion():
    timing = RopeTimingEstimator(initial_period=1.25)
    assert timing.should_jump(True, 10.0) is True
    assert timing.should_jump(True, 11.0) is True
    assert timing.period == pytest.approx(1.18)
    assert timing.should_jump(False, 12.19) is True


def test_non_positive_duration_is_rejected():
    bot = JumpRopeBot()
    with pytest.raises(ValueError):
        bot.run(0)
