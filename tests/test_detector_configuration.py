"""Guard the production detector configuration."""

from jump_rope_bot import BotConfig, VisualPassDetector
from jump_detector import VisualPassDetector as Selected


def test_frontend_controller_uses_selected_detector():
    assert VisualPassDetector is Selected
    detector = Selected()
    assert detector.repair_snap_clock
    assert not detector.repair_floor_gap
    assert detector.name == 'speed2' and detector.tracker.fast
    assert (detector.tracker.width, detector.tracker.height) == (960, 540)
    assert BotConfig().key_down_time == .025
