"""Production contracts: timing, actor/rope state and fail-safe input ownership."""
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import pytest
import numpy as np
import jump_rope_bot as bot_module
from jump_rope_bot import JumpRopeBot,BotConfig
from timing_control import control_config,offset_ms
from controller.policy import ArcCarryPolicy
from controller.decision import BoxDecision
from input_pulse import Pulse,InputRejected


@pytest.mark.parametrize('position,offset',[(0,-40),(.25,-20),(.5,0),(.75,20),(1,40),(.503,.24)])
def test_timing_is_continuous_and_direction_matches_labels(position,offset):
    assert offset_ms(position)==pytest.approx(offset)
    config=control_config(position)
    assert config['floor_lead_ms']==pytest.approx(268.95-offset)
    assert config['arc_lead_ms']==pytest.approx(168.95-offset)
    assert config['hold_ms']==25
    original=control_config(.5)
    for key in config:
        if key not in ('floor_lead_ms','arc_lead_ms'):assert config[key]==original[key]


@pytest.mark.parametrize('value',[-.01,1.01,float('nan'),float('inf'),True,'0.5'])
def test_invalid_slider_values_never_reach_controller(value):
    with pytest.raises(ValueError):control_config(value)


def test_policy_reset_cancels_reservations_and_input_history():
    p=ArcCarryPolicy('release',control_config())
    p.floor_pending={'event_ns':1000};p.arc_pending={'event_ns':2000};p.commit_jump(10)
    p.reset()
    assert p.floor_pending is None and p.arc_pending is None
    assert p.last_down is None and p.actor.last_down_ns is None


@pytest.fixture
def simulated(monkeypatch):
    frame=np.zeros((540,960,3),np.uint8)
    native=[];seen=[]
    monkeypatch.setattr(bot_module.win32gui,'GetForegroundWindow',lambda:123)
    monkeypatch.setattr(bot_module.win32gui,'GetClientRect',lambda _:(0,0,960,540))
    monkeypatch.setattr(bot_module.win32gui,'ClientToScreen',lambda _,p:p)
    monkeypatch.setattr(bot_module.win32api,'GetCursorPos',lambda:(820,440))
    monkeypatch.setattr(bot_module.win32api,'SetCursorPos',lambda _:None)
    monkeypatch.setattr(bot_module.win32api,'mouse_event',lambda flag,*_:native.append((flag,time.perf_counter_ns())))
    bot=JumpRopeBot(BotConfig(diagnostics_enabled=False,auto_start=True,round_timeout=30),
        detector=SimpleNamespace(observe=lambda *_a,**_kw:SimpleNamespace(rope_xyxy=(0,0,960,400))),
        pulse_factory=Pulse)
    bot.focus_game=lambda:setattr(bot,'_hwnd',123) or 123
    class Gate:
        finished=False
        n=0
        @classmethod
        def reset_cache(cls):pass
        @classmethod
        def gameplay_visible(cls,_):return True
        @classmethod
        def jump_position(cls,_):return (820/960,440/540)
        def observe(self,_):
            self.n+=1;self.finished=self.n>=7
            return not self.finished
    bot.gate_type=Gate
    class Policy:
        last_diagnostic={}
        def observe(self,_p,stamp,_shape,now_ns):
            return BoxDecision(len(seen)==1,'test',stamp,stamp+30_000_000,ready=True)
        def commit_jump(self,_):pass
        def reset(self):pass
        def mark_loss(self,_):pass
        def invalidate_observation(self):pass
    bot.control=Policy()
    class Capture:
        closed=False
        def __init__(self,*_,**__):pass
        def grab(self):
            time.sleep(.005);seen.append(time.perf_counter_ns());return frame.copy()
        def close(self):self.closed=True
    monkeypatch.setattr(bot_module,'GameCapture',Capture)
    return bot,native,seen


def test_complete_round_captures_while_25ms_key_is_held(simulated):
    bot,native,seen=simulated
    bot.run()
    assert bot.stop_reason=='round_finished' and bot.tap_count==1
    assert [r[0] for r in native]==[bot_module.win32con.MOUSEEVENTF_LEFTDOWN,bot_module.win32con.MOUSEEVENTF_LEFTUP]
    assert any(native[0][1]<stamp<native[1][1] for stamp in seen)
    assert bot.pulse._thread.is_alive() is False


@pytest.mark.parametrize('fault',['focus','capture','resize','writer','stop'])
def test_faults_after_down_release_and_do_not_continue(simulated,monkeypatch,fault):
    bot,native,seen=simulated
    real=bot.detector.observe
    def observe(*args,**kwargs):
        if len(seen)==2:
            if fault=='focus':monkeypatch.setattr(bot_module.win32gui,'GetForegroundWindow',lambda:999)
            elif fault=='stop':bot.stop()
            elif fault=='writer':raise RuntimeError('diagnostic write failed')
            elif fault=='capture':raise RuntimeError('capture failed')
            elif fault=='resize':monkeypatch.setattr(bot_module.win32gui,'GetClientRect',lambda _:(0,0,100,100))
        return real(*args,**kwargs)
    bot.detector.observe=observe
    if fault=='resize':
        # Force one subsequent proposal to exercise the native size recheck.
        old=bot.control.observe
        bot.control.observe=lambda *a,**k:replace(old(*a,**k),jump=len(seen)>=3)
    if fault in ('writer','capture'):
        with pytest.raises(RuntimeError):bot.run()
    else:bot.run()
    assert len(native)%2==0
    assert all(native[i][0]==bot_module.win32con.MOUSEEVENTF_LEFTUP for i in range(1,len(native),2))
    assert not bot.pulse._thread.is_alive()


def test_expired_down_is_rejected_before_any_os_input(simulated):
    bot,native,_=simulated;bot._hwnd=123
    context=dict(source_size=(960,540),frame_id=0,expires_ns=time.perf_counter_ns()-1)
    with pytest.raises(InputRejected):bot._native('down',context)
    assert native==[]


@pytest.mark.parametrize('age_ms,accepted',[(19,True),(25,True),(25.1,True),(29.9,True),(31,False)])
def test_gpu_native_input_uses_original_capture_deadline(simulated,monkeypatch,age_ms,accepted):
    bot,native,_=simulated;bot._hwnd=123
    stamp=1_000_000_000
    monkeypatch.setattr(bot_module.time,'perf_counter_ns',lambda:stamp+age_ms*1_000_000)
    context=dict(source_size=(960,540),frame_id=0,expires_ns=stamp+30_000_000,
                 capture_ns=stamp,down_ns=None)
    if accepted:
        bot._native('down',context)
        bot._native('up',context,'test')
        assert len(native)==2 and bot.input_pulses[0]['capture_return_to_down_ms']==age_ms
    else:
        with pytest.raises(InputRejected):bot._native('down',context)
        assert native==[]


@pytest.mark.parametrize('age_ms',[40,80,200])
def test_default_no_fixed_expiry_reaches_native_and_releases(simulated,monkeypatch,age_ms):
    bot,native,_=simulated;bot._hwnd=123
    stamp=1_000_000_000
    monkeypatch.setattr(bot_module.time,'perf_counter_ns',lambda:stamp+age_ms*1_000_000)
    context=dict(source_size=(960,540),frame_id=0,expires_ns=None,capture_ns=stamp,down_ns=None)
    bot._native('down',context);bot._native('up',context,'test')
    assert len(native)==2 and control_config()['frame_validity_ms'] is None


def test_no_fixed_expiry_pulse_still_releases_on_stop():
    calls=[]
    pulse=Pulse(lambda _:calls.append('down') or time.perf_counter_ns(),lambda _,reason:calls.append(('up',reason)))
    try:
        assert pulse.press({},valid_until_ns=None)
        pulse.reset('stop')
    finally:pulse.close()
    assert calls==['down',('up','stop')] and not pulse._thread.is_alive()


@pytest.mark.parametrize('fault',['focus','stop','resize','superseded'])
def test_unbounded_age_preserves_native_state_guards(simulated,monkeypatch,fault):
    bot,native,_=simulated;bot._hwnd=123
    if fault=='focus':monkeypatch.setattr(bot_module.win32gui,'GetForegroundWindow',lambda:999)
    if fault=='stop':bot.stop()
    if fault=='resize':monkeypatch.setattr(bot_module.win32gui,'GetClientRect',lambda _:(0,0,100,100))
    context=dict(source_size=(960,540),frame_id=-1 if fault=='superseded' else 0,expires_ns=None)
    with pytest.raises(InputRejected):bot._native('down',context)
    assert native==[]


def test_archive_files_are_byte_identical_to_snapshot():
    import hashlib
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'archive/snapshot.json').read_text())
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((root/'archive/v1.2.1'/name).read_bytes()).hexdigest()==digest
