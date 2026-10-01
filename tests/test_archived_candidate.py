"""Preserve v19–v21 timing findings separately from the released v18b gate.

These contracts test an archived offline candidate, not the application's
default strategy. The final three seven-round trials did not improve scores.
"""
import json
from pathlib import Path

from experiments.rope_track_v21b import RopePosition, VisualPassDetector


def events_for(name):
    source = Path(__file__).parent / 'fixtures' / 'gate' / name
    detector = VisualPassDetector()
    events = []
    for t, h, c, color, contrast in json.loads(source.read_text(encoding='utf-8'))['measurements']:
        detector.tracker.locate = lambda _, pos=RopePosition(h, c, 0, color, contrast): pos
        if detector.observe(None, t):
            events.append(t)
    return events


def test_archived_blue_reappearance_after_336ms():
    events = events_for('v18-round-1.json')
    assert [t for t in events if 127.90 <= t <= 128.40] == [128.2285]


def test_archived_floor_reappearance_after_three_missing_observations():
    events = events_for('v18-round-6.json')
    assert [t for t in events if 79.9 <= t <= 80.3] == [80.0563]


def test_archived_persistent_partial_prop_snap():
    events = events_for('v18-round-3.json')
    assert not any(39.20 <= t <= 39.27 for t in events)
    assert [t for t in events if 39.30 <= t <= 39.50] == [39.3723]


def test_archived_rejected_snap_cannot_age_into_premature_pass():
    events = events_for('v19b-round-7.json')
    assert not any(63.35 <= t <= 63.45 for t in events)
    assert [t for t in events if 63.60 <= t <= 63.80] == [63.6765]
