"""Bounded batch mode must not advance from unknown or interrupted states."""

import sys
import pytest
import runpy
from pathlib import Path
from types import SimpleNamespace

from tools import run_round_test as runner


def test_double_click_entry_defaults_to_seven(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, 'run_round_test', SimpleNamespace(
        main=lambda **kw: calls.append(kw) or 0))
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(Path(runner.__file__).with_name('run_batch_test.py')), run_name='__main__')
    assert error.value.code == 0
    assert calls == [{'default_rounds': 7}]


@pytest.mark.parametrize('rounds', ['0', '8', '-1'])
def test_batch_rejects_out_of_bounds_before_creating_bot(monkeypatch, rounds):
    monkeypatch.setattr(sys, 'argv', ['batch', '--rounds', rounds])
    monkeypatch.setattr(runner.win32event, 'CreateMutex',
                        lambda *_: pytest.fail('started invalid batch'))
    with pytest.raises(SystemExit) as error:
        runner.main(default_rounds=7)
    assert error.value.code == 2


def test_result_page_requires_five_stable_frames(monkeypatch):
    frames = iter(["next", "next", None, "next", "next", "next", "next", "next"])
    now = [0.]

    class Capture:
        def __init__(self, hwnd):
            assert hwnd == 123

        def grab(self):
            return next(frames)

    class Screen:
        def identify(self, frame):
            return frame

    monkeypatch.setattr(runner.RoundGate, "gameplay_visible", lambda _: False)
    monkeypatch.setattr(runner.win32gui, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(runner.win32api, "GetAsyncKeyState", lambda _: 0)
    assert runner.wait_for_result_page(
        123, clock=lambda: now[0], sleeper=lambda t: now.__setitem__(0, now[0] + t),
        capture_factory=Capture, screen_factory=Screen,
    )


def test_result_page_never_advances_on_focus_loss(monkeypatch):
    class Capture:
        def __init__(self, _hwnd):
            pass

        def grab(self):
            raise AssertionError("captured after focus loss")

    monkeypatch.setattr(runner.win32gui, "GetForegroundWindow", lambda: 999)
    assert not runner.wait_for_result_page(123, capture_factory=Capture)


@pytest.mark.parametrize('rounds', [3, 7])
def test_batch_runs_exact_bound_and_never_checks_result_after_final(monkeypatch, tmp_path, rounds):
    seen = []
    checks = []

    class Bot:
        def __init__(self, config):
            seen.append(config.record_path)
            self.stop_reason = "round_finished"
            self.round_started_at = 1.
            self._hwnd = 123
            self.candidate_count = 0
            self.tap_count = 0

        def run(self):
            pass

    monkeypatch.setattr(runner, "JumpRopeBot", Bot)
    monkeypatch.setattr(runner, "wait_for_result_page",
                        lambda hwnd: checks.append(hwnd) or True)
    monkeypatch.setattr(runner.win32event, "CreateMutex", lambda *_: 321)
    monkeypatch.setattr(runner.win32api, "GetLastError", lambda: 0)
    monkeypatch.setattr(runner.win32api, "CloseHandle", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["batch", "--record", str(tmp_path / "test.mp4")])
    assert runner.main(default_rounds=rounds) == 0
    assert [path.name for path in seen] == [f"test-round-{i:02d}.mp4" for i in range(1, rounds+1)]
    assert checks == [123] * (rounds-1)


def test_batch_stops_when_round_did_not_finish(monkeypatch, tmp_path):
    seen = []

    class Bot:
        def __init__(self, config):
            seen.append(config.record_path)
            self.stop_reason = "focus_lost"
            self.round_started_at = 1.
            self._hwnd = 123
            self.candidate_count = 0
            self.tap_count = 0

        def run(self):
            pass

    monkeypatch.setattr(runner, "JumpRopeBot", Bot)
    monkeypatch.setattr(runner, "wait_for_result_page",
                        lambda _: (_ for _ in ()).throw(AssertionError("advanced")))
    monkeypatch.setattr(runner.win32event, "CreateMutex", lambda *_: 321)
    monkeypatch.setattr(runner.win32api, "GetLastError", lambda: 0)
    monkeypatch.setattr(runner.win32api, "CloseHandle", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["batch", "--record", str(tmp_path / "test.mp4")])
    assert runner.main(default_rounds=7) == 2
    assert len(seen) == 1
