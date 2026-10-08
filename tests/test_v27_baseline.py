"""Guard the selected public entry point and its published frozen core."""
import hashlib
import json
from pathlib import Path

from jump_rope_bot import BotConfig, VisualPassDetector
from v27_detector import VisualPassDetector as Selected


def test_frontend_controller_uses_only_selected_v27():
    assert VisualPassDetector is Selected
    detector = Selected()
    assert detector.repair_snap_clock
    assert not detector.repair_floor_gap
    assert detector.name == 'speed2' and detector.tracker.fast
    assert (detector.tracker.width, detector.tracker.height) == (960, 540)
    assert BotConfig().key_down_time == .025


def test_core_matches_published_baseline_after_line_ending_normalization():
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root/'docs/v27-core.json').read_text(encoding='utf-8'))
    for name, expected in record['canonical_core_sha256'].items():
        actual = hashlib.sha256((root/name).read_text(encoding='utf-8').encode('utf-8')).hexdigest()
        assert actual == expected, name
