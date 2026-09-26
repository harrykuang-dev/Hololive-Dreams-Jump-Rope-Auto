import json

import cv2
import numpy as np
import pytest

from jump_rope_bot import BotConfig, JumpRopeBot
from round_recording import RoundRecorder


def test_round_recording_keeps_video_and_input_timestamps(tmp_path):
    path = tmp_path / "single-round.mp4"
    frame = np.full((65, 101, 3), (40, 90, 160), dtype=np.uint8)
    recorder = RoundRecorder(path, frame)
    recorder.add(frame, .04, hud=True, ready=True, candidate=True,
                 clicked=True, detector_score=.8, input_elapsed=.041)
    log_path = recorder.close(stop_reason="round_finished", tap_count=1,
                              candidate_count=1, error=None)

    capture = cv2.VideoCapture(str(path))
    ok, decoded = capture.read()
    capture.release()
    assert ok
    assert decoded.shape[:2] == (66, 102)
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["stop_reason"] == "round_finished"
    assert log["tap_count"] == 1
    assert log["frames"] == [{
        "t": .04, "hud": True, "ready": True, "candidate": True,
        "clicked": True, "input_t": .041, "detector_score": .8,
    }]


def test_recording_path_must_be_mp4(tmp_path):
    with pytest.raises(ValueError, match=".mp4"):
        JumpRopeBot(BotConfig(record_path=tmp_path / "round.avi"))
