import threading
from types import SimpleNamespace

import pytest

import batch_session as module
from batch_session import BatchSession, SessionConfig
from jump_rope_bot import JumpRopeBot


@pytest.fixture
def mutex(monkeypatch):
    closed = []
    monkeypatch.setattr(module.win32event, 'CreateMutex', lambda *_: 123)
    monkeypatch.setattr(module.win32api, 'GetLastError', lambda: 0)
    monkeypatch.setattr(module.win32api, 'CloseHandle', closed.append)
    return closed


@pytest.mark.parametrize('rounds', [0, 8, -1, 1.5, True])
def test_invalid_round_limit(rounds):
    with pytest.raises(ValueError):
        SessionConfig(rounds=rounds).validate()


def test_session_bound_and_final_round_never_navigates(mutex):
    seen, checked = [], []

    def factory(config, stop_requested):
        seen.append(config)
        assert not stop_requested()
        return SimpleNamespace(run=lambda: None, tap_count=10,
                               stop_reason='round_finished', round_started_at=1, _hwnd=999)

    session = BatchSession(SessionConfig(rounds=7), bot_factory=factory,
        result_wait=lambda hwnd, **kw: checked.append(hwnd) or True, get_key_state=lambda _: 0)
    session.run()
    assert len(seen) == session.completed_rounds == 7
    assert checked == [999]*6
    assert session.inputs == 70
    assert mutex == [123]
    assert all(c.record_path is None and c.capture_backend == 'dxgi' for c in seen)


def test_stop_between_rounds_cannot_start_another_bot(mutex):
    seen = []
    session = None

    def factory(config, **_):
        seen.append(config)
        return SimpleNamespace(run=lambda: None, tap_count=2,
                               stop_reason='round_finished', round_started_at=1, _hwnd=999)

    def result_wait(_hwnd, stop_requested, **_):
        session.stop()
        assert stop_requested()
        return False

    session = BatchSession(SessionConfig(rounds=7), bot_factory=factory,
                           result_wait=result_wait, get_key_state=lambda _: 0)
    session.run()
    assert len(seen) == 1
    assert session.completed_rounds == 1
    assert mutex == [123]


def test_prestart_stop_is_not_cleared_by_bot_run(mutex, monkeypatch):
    event = threading.Event()
    event.set()
    bot = JumpRopeBot(stop_requested=event.is_set)
    monkeypatch.setattr(bot, 'focus_game', lambda: pytest.fail('focused after external stop'))
    bot.run()
    assert bot.stop_reason == 'stopped'
    assert not bot.running


def test_f9_remains_available_with_custom_shortcut(mutex):
    session = BatchSession(SessionConfig(stop_hotkey='Ctrl+Alt+Q'),
                           get_key_state=lambda key: 0x8000 if key == 0x78 else 0)
    session.run()
    assert session.current_bot is None
    assert session.stop_reason == 'stopped'
    assert mutex == [123]


def test_interrupted_round_never_checks_result_page(mutex):
    bot = SimpleNamespace(run=lambda: None, tap_count=2,
                          stop_reason='focus_lost', round_started_at=1, _hwnd=999)
    session = BatchSession(SessionConfig(rounds=7), bot_factory=lambda *_a, **_kw: bot,
        result_wait=lambda *_a, **_kw: pytest.fail('advanced after interruption'), get_key_state=lambda _: 0)
    session.run()
    assert session.completed_rounds == 0
    assert session.inputs == 2
    assert session.stop_reason == 'focus_lost'


def test_single_instance_rejection_never_creates_bot(mutex, monkeypatch):
    monkeypatch.setattr(module.win32api, 'GetLastError', lambda: module.winerror.ERROR_ALREADY_EXISTS)
    session = BatchSession(SessionConfig(), bot_factory=lambda *_a, **_kw: pytest.fail('duplicate bot'))
    with pytest.raises(RuntimeError, match='already running'):
        session.run()
    assert mutex == [123]
