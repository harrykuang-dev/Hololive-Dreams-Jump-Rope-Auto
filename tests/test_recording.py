import json
import threading

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
                              candidate_count=1, error=None, input_times=[.041])

    capture = cv2.VideoCapture(str(path))
    ok, decoded = capture.read()
    capture.release()
    assert ok
    assert decoded.shape[:2] == (66, 102)
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["stop_reason"] == "round_finished"
    assert log["tap_count"] == 1
    assert log["input_times"] == [.041]
    assert log["frames"] == [{
        "t": .04, "hud": True, "ready": True, "candidate": True,
        "clicked": True, "input_t": .041, "detector_score": .8,
    }]


def test_recording_path_must_be_mp4(tmp_path):
    with pytest.raises(ValueError, match=".mp4"):
        JumpRopeBot(BotConfig(record_path=tmp_path / "round.avi"))


def test_async_60fps_recording_keeps_exact_frame_mapping_and_actual_rate(tmp_path):
    frame = np.zeros((540, 960, 3), np.uint8)
    recorder = RoundRecorder(tmp_path/'60.mp4', frame, fps=60)
    for i in range(5):
        frame[:] = 30+i*40
        recorder.add(frame, i*.04, hud=True, ready=True, candidate=False,
                     clicked=False, detector_score=0, telemetry={'phase': 'round'})
    path = recorder.close(stop_reason='round_finished', tap_count=0,
                          candidate_count=0, error=None)
    log = json.loads(path.read_text(encoding='utf-8'))
    assert log['video_fps'] == 60
    assert log['performance']['actual_round_fps'] == pytest.approx(25)
    assert log['encoding_complete']
    assert log['written_video_frames'] == 5
    cap = cv2.VideoCapture(str(tmp_path/'60.mp4'))
    assert cap.get(cv2.CAP_PROP_FPS) == 60
    for i in range(5):
        ok, decoded = cap.read()
        assert ok and float(decoded.mean()) == pytest.approx(30+i*40, abs=5)
    assert not cap.read()[0]
    cap.release()


def test_encoder_failure_is_reported_in_json_and_raised(tmp_path, monkeypatch):
    import round_recording as module
    failed = threading.Event()

    class BrokenWriter:
        def isOpened(self): return True
        def write(self, _frame):
            raise OSError('simulated disk failure')
        def release(self): failed.set()

    monkeypatch.setattr(module.cv2, 'VideoWriter', lambda *args: BrokenWriter())
    frame = np.zeros((20, 20, 3), np.uint8)
    recorder = RoundRecorder(tmp_path/'failed.mp4', frame)
    recorder.add(frame, 0, hud=True, ready=True, candidate=False, clicked=False, detector_score=0)
    assert failed.wait(2)
    with pytest.raises(RuntimeError, match='simulated disk failure'):
        recorder.check_health()
    with pytest.raises(RuntimeError):
        recorder.close(stop_reason='round_finished', tap_count=0, candidate_count=0, error=None)
    log = json.loads((tmp_path/'failed.events.json').read_text(encoding='utf-8'))
    assert log['stop_reason'] == 'recording_error'
    assert not log['encoding_complete']


def test_bounded_encoder_queue_never_silently_drops_frames(tmp_path, monkeypatch):
    import round_recording as module
    entered, release = threading.Event(), threading.Event()

    class SlowWriter:
        def isOpened(self): return True
        def write(self, _frame):
            entered.set()
            assert release.wait(2)
        def release(self): pass

    monkeypatch.setattr(module.cv2, 'VideoWriter', lambda *args: SlowWriter())
    frame = np.zeros((20, 20, 3), np.uint8)
    recorder = RoundRecorder(tmp_path/'full.mp4', frame, queue_size=1)
    args = dict(hud=True, ready=True, candidate=False, clicked=False, detector_score=0)
    try:
        recorder.add(frame, 0, **args)
        assert entered.wait(2)
        recorder.add(frame, .02, **args)
        with pytest.raises(RuntimeError, match='佇列'):
            recorder.add(frame, .04, **args)
        assert len(recorder.frames) == 2
    finally:
        release.set()
        # The fake writer emits no actual MP4, so integrity verification fails.
        with pytest.raises(RuntimeError):
            recorder.close(stop_reason='error', tap_count=0, candidate_count=0, error='queue full')


def test_default_buffer_survives_brief_stall_with_exact_video_mapping(tmp_path, monkeypatch):
    import round_recording as module
    entered, resume = threading.Event(), threading.Event()
    real_writer = cv2.VideoWriter

    class PausedWriter:
        def __init__(self, *args): self.writer = real_writer(*args)
        def isOpened(self): return self.writer.isOpened()
        def write(self, frame):
            entered.set()
            assert resume.wait(2)
            self.writer.write(frame)
        def release(self): self.writer.release()

    monkeypatch.setattr(module.cv2, 'VideoWriter', PausedWriter)
    frame = np.zeros((20, 20, 3), np.uint8)
    recorder = RoundRecorder(tmp_path/'stall.mp4', frame)
    args = dict(hud=True, ready=True, candidate=False, clicked=False, detector_score=0)
    try:
        recorder.add(frame, 0, **args)
        assert entered.wait(2)
        for i in range(1, 21):
            frame[:] = i*10
            recorder.add(frame, i/60, **args)
        recorder.check_health()
        assert recorder.queue_peak == 20
    finally:
        resume.set()
        path = recorder.close(stop_reason='round_finished', tap_count=0,
                              candidate_count=0, error=None)
    log = json.loads(path.read_text(encoding='utf-8'))
    assert log['encoding_complete'] and log['written_video_frames'] == 21
    assert log['performance']['queue_capacity'] == 32
    assert log['performance']['encode_max_ms'] >= log['performance']['encode_median_ms']
    cap = cv2.VideoCapture(str(tmp_path/'stall.mp4'))
    for i in range(21):
        ok, decoded = cap.read()
        assert ok and decoded.mean() == pytest.approx(i*10, abs=5)
    assert not cap.read()[0]
    cap.release()


def test_controller_checks_encoder_before_any_candidate_input(tmp_path, monkeypatch):
    import jump_rope_bot as controller
    from tests.test_bot import live_frame
    from rope_track import RopePosition

    class Capture:
        def __init__(self, _): pass
        def grab(self): return live_frame()

    class Recorder:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs): pass
        def check_health(self): raise RuntimeError('encoder failed')
        def close(self, **kwargs): pass

    class Detector:
        position = RopePosition(0, 1, 0)
        last_score = 1
        def observe(self, *args): return True

    bot = JumpRopeBot(BotConfig(record_path=tmp_path/'guard.mp4', result_postroll=0))
    monkeypatch.setattr(bot, 'focus_game', lambda: setattr(bot, '_hwnd', 123))
    monkeypatch.setattr(controller, 'GameCapture', Capture)
    monkeypatch.setattr(controller, 'RoundRecorder', Recorder)
    monkeypatch.setattr(controller, 'VisualPassDetector', Detector)
    monkeypatch.setattr(controller.RoundGate, 'observe', lambda *args: True)
    monkeypatch.setattr(controller.win32gui, 'GetForegroundWindow', lambda: 123)
    monkeypatch.setattr(controller.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(bot, 'tap_jump', lambda _: pytest.fail('input after encoder failure'))
    with pytest.raises(RuntimeError, match='encoder failed'):
        bot.run()
    assert bot.tap_count == 0 and bot.stop_reason == 'error'
