"""Minimized-start regressions; no desktop capture or input is performed."""
from types import SimpleNamespace
import pytest
import win32process
import jump_rope_bot as module


@pytest.fixture
def restore(monkeypatch):
    state = SimpleNamespace(now=0.,iconic=True,foreground=456,restore_at=.25,
                            width=1920,height=1080,requests=0,stop_at=None)
    bot = module.JumpRopeBot(clock=lambda:state.now)
    def sleep(seconds):
        state.now += seconds
        if state.restore_at is not None and state.now >= state.restore_at:
            state.iconic = False
        if state.stop_at is not None and state.now >= state.stop_at:
            bot.stop()
    bot._sleep = sleep
    monkeypatch.setattr(bot,'find_game',lambda:123)
    monkeypatch.setattr(bot,'_allow_foreground_switch',lambda:None)
    def restore_window(hwnd,_command):
        assert hwnd.value == 123
        state.requests += 1
        return 1
    monkeypatch.setattr(module.ctypes.windll.user32,'ShowWindowAsync',restore_window)
    monkeypatch.setattr(module.win32gui,'IsWindow',lambda _hwnd:True)
    monkeypatch.setattr(module.win32gui,'IsIconic',lambda _hwnd:state.iconic)
    monkeypatch.setattr(module.win32gui,'GetForegroundWindow',lambda:state.foreground)
    monkeypatch.setattr(module.win32gui,'SetForegroundWindow',lambda hwnd:setattr(state,'foreground',hwnd))
    monkeypatch.setattr(module.win32gui,'GetClientRect',lambda _hwnd:(0,0,state.width,state.height))
    monkeypatch.setattr(module.win32gui,'ShowWindow',lambda *_:pytest.fail('synchronous restore'))
    monkeypatch.setattr(module.win32gui,'SetFocus',lambda *_:pytest.fail('cross-thread focus'))
    monkeypatch.setattr(win32process,'AttachThreadInput',lambda *_:pytest.fail('shared input queues'))
    return bot,state


def test_minimized_start_waits_for_restored_foreground_before_capture(restore):
    bot,state = restore
    assert bot.focus_game() == 123
    assert not state.iconic and state.foreground == 123
    assert state.now >= .4
    assert state.requests == 1


def test_stop_during_restore_does_not_create_capture(restore,monkeypatch):
    bot,state = restore
    state.stop_at = .1
    monkeypatch.setattr(module,'GameCapture',lambda *_a,**_kw:pytest.fail('capture after stop'))
    bot._loop()
    assert bot.stop_reason == 'stopped'
    assert state.now < .2
    assert not bot.running


@pytest.mark.parametrize('problem',['still_minimized','zero_size','focus_denied'])
def test_failed_restore_is_bounded_and_never_captures(restore,monkeypatch,problem):
    bot,state = restore
    if problem == 'still_minimized':
        state.restore_at = None
    elif problem == 'zero_size':
        state.width = 0
    else:
        monkeypatch.setattr(module.win32gui,'SetForegroundWindow',lambda _hwnd:None)
    monkeypatch.setattr(module,'GameCapture',lambda *_a,**_kw:pytest.fail('capture before restoration'))
    with pytest.raises(RuntimeError,match='無法還原'):
        bot.run()
    assert 3.0 <= state.now < 3.1
    assert bot.stop_reason == 'error'
    assert not bot.running
