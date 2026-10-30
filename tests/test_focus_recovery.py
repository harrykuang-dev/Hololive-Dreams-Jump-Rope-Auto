from types import SimpleNamespace
import json,zipfile
import pytest
import focus_recovery as f

@pytest.fixture
def state(monkeypatch):
 s=SimpleNamespace(fg=2,now=0.,keys=[],calls=[],stop=False,allowed=True,exists=True,alt=False)
 monkeypatch.setattr(f.win32gui,'GetForegroundWindow',lambda:s.fg)
 monkeypatch.setattr(f.win32gui,'IsWindow',lambda h:s.exists)
 monkeypatch.setattr(f.win32gui,'IsIconic',lambda h:False)
 monkeypatch.setattr(f.win32gui,'GetClientRect',lambda h:(0,0,960,540))
 def activate(h):
  s.calls.append(h)
  if s.allowed:s.fg=h
 monkeypatch.setattr(f.win32gui,'SetForegroundWindow',activate)
 monkeypatch.setattr(f.win32api,'GetAsyncKeyState',lambda k:0x8000 if s.alt else 0)
 monkeypatch.setattr(f.win32api,'keybd_event',lambda v,scan,flag,e:s.keys.append(flag))
 monkeypatch.setattr(f.ctypes.windll.user32,'AllowSetForegroundWindow',lambda *a:True)
 monkeypatch.setattr(f,'window_snapshot',lambda h:dict(hwnd=h,title='Other app' if h==2 else 'Game',pid=123))
 s.make=lambda **kw:f.FocusRecovery(clock=lambda:s.now,sleeper=lambda t:setattr(s,'now',s.now+t),**kw)
 return s

def test_second_loss_never_activates_and_logs_thief(state):
 m=state.make(diagnostics=True);released=[]
 for n in range(1):
  state.fg=2;assert m.ensure(1,stopped=lambda:False,release=lambda:released.append(n))
 state.fg=2;assert not m.ensure(1,stopped=lambda:False,release=lambda:released.append(1))
 assert m.attempts==m.successes==len(state.calls)==1 and len(released)==2
 assert state.keys==[0,2]
 assert [e for e in m.events if e['event']=='focus_lost'][0]['foreground']['title']=='Other app'

@pytest.mark.parametrize('diagnostics',[False,True])
def test_denied_focus_maximum_one(state,diagnostics):
 state.allowed=False;m=state.make(diagnostics=diagnostics)
 assert not m.ensure(1,stopped=lambda:False)
 assert m.attempts==len(state.calls)==1 and state.keys==[0,2]
 if not diagnostics:assert not m.events

@pytest.mark.parametrize('stop_point',['before','alt','wait'])
def test_stop_releases_alt_and_does_not_retry(state,monkeypatch,stop_point):
 m=state.make();released=[]
 if stop_point=='before':state.stop=True
 if stop_point=='alt':
  def key(v,scan,flag,e):
   state.keys.append(flag)
   if flag==0:state.stop=True
  monkeypatch.setattr(f.win32api,'keybd_event',key)
 if stop_point=='wait':
  state.allowed=False;m.sleep=lambda t:setattr(state,'stop',True)
 assert not m.ensure(1,stopped=lambda:state.stop,release=lambda:released.append(True))
 assert released and m.attempts<=1
 assert not state.keys or state.keys==[0,2]
 if stop_point!='wait':assert not state.calls

def test_manual_alt_not_released(state):
 state.alt=True;m=state.make();assert m.ensure(1,stopped=lambda:False);assert not state.keys

def test_game_closed_no_activation(state):
 state.exists=False;m=state.make();assert not m.ensure(1,stopped=lambda:False);assert not state.calls

def test_already_focused_no_budget_or_queries(state,monkeypatch):
 state.fg=1;m=state.make(diagnostics=True)
 monkeypatch.setattr(f,'window_snapshot',lambda h:pytest.fail('query on normal frame'))
 assert m.ensure(1,stopped=lambda:False);assert m.attempts==0 and not m.events

def test_diagnostics_off_no_titles(state,monkeypatch):
 m=state.make();monkeypatch.setattr(f,'window_snapshot',lambda h:pytest.fail('title collected while disabled'))
 assert m.ensure(1,stopped=lambda:False)

def test_activate_exception_releases_alt(state,monkeypatch):
 state.allowed=False
 monkeypatch.setattr(f.win32gui,'SetForegroundWindow',lambda h:(_ for _ in ()).throw(OSError('denied')))
 m=state.make();assert not m.ensure(1,stopped=lambda:False);assert state.keys==[0,2]

def test_controller_releases_before_activation_and_invalidates(state,monkeypatch):
 from jump_rope_bot import JumpRopeBot
 bot=JumpRopeBot(focus_recovery=state.make());bot._hwnd=1;events=[]
 bot.pulse=SimpleNamespace(error=None,reset=lambda reason:events.append('released'))
 bot.control=SimpleNamespace(reset=lambda:events.append('reset'))
 monkeypatch.setattr(f.win32gui,'SetForegroundWindow',lambda h:(events.append('activate'),setattr(state,'fg',h)))
 assert bot.ensure_foreground();assert events[:3]==['released','reset','activate'];assert bot._capture_restart

@pytest.mark.parametrize('failure',['none','model','pack'])
def test_zero_frame_session_has_zip_or_preserves_files(tmp_path,monkeypatch,failure):
 import batch_session as b
 import detector
 import hardware_diagnostics
 monkeypatch.setattr(hardware_diagnostics,'collect_system',lambda _:{'mock_inventory':True})
 monkeypatch.setattr(b.win32event,'CreateMutex',lambda *a:123)
 monkeypatch.setattr(b.win32api,'GetLastError',lambda:0)
 monkeypatch.setattr(b.win32api,'CloseHandle',lambda h:None)
 def factory(config,stop_requested):return SimpleNamespace(run=lambda:None,tap_count=0,stop_reason='focus_lost',round_started_at=None,_hwnd=1)
 if failure=='model':
  monkeypatch.setattr(detector,'FullFrameDetector',lambda **kw:(_ for _ in ()).throw(RuntimeError('initialization failed')))
  factory=b.JumpRopeBot
 session=b.BatchSession(b.SessionConfig(diagnostics=True),bot_factory=factory,get_key_state=lambda k:0,base=tmp_path)
 if failure=='pack':monkeypatch.setattr(session,'_session_package',lambda:(_ for _ in ()).throw(OSError('disk')))
 if failure=='model':
  with pytest.raises(RuntimeError):session.run()
 else:session.run()
 content=json.loads((session.directory/'diagnostics.json').read_text(encoding='utf-8'))
 assert content['system']['mock_inventory']
 assert content['events'][-1]['type']=='session_finished'
 if failure=='model':assert 'initialization failed' in content['events'][-1]['error']['message']
 if failure!='pack':
  with zipfile.ZipFile(session.directory/'diagnostics.zip') as z:
   assert z.testzip() is None and z.namelist()==['diagnostics.json']
 else:assert session.stop_reason=='focus_lost'

def test_budget_shared_across_real_session_rounds(state,tmp_path,monkeypatch):
 import batch_session as b
 import detector
 monkeypatch.setattr(b.win32event,'CreateMutex',lambda *a:123)
 monkeypatch.setattr(b.win32api,'GetLastError',lambda:0)
 monkeypatch.setattr(b.win32api,'CloseHandle',lambda h:None)
 monkeypatch.setattr(detector,'FullFrameDetector',lambda **kw:SimpleNamespace(backend='onnx-directml',runtime=SimpleNamespace(adapter={}),fallback_reason=None))
 managers=[]
 class Bot:
  def __init__(self,config,focus_recovery,**kw):
   self.m=focus_recovery;managers.append(self.m);self.tap_count=0;self._hwnd=1;self.round_started_at=1
  def run(self):
   state.fg=2;ok=self.m.ensure(1,stopped=lambda:False);self.stop_reason='round_finished' if ok else 'focus_lost'
 monkeypatch.setattr(b,'JumpRopeBot',Bot)
 s=b.BatchSession(b.SessionConfig(rounds=5),bot_factory=Bot,result_wait=lambda *a,**kw:True,get_key_state=lambda k:0)
 s.focus_recovery=state.make();s.run()
 assert s.completed_rounds==1 and len(managers)==2 and len({id(m) for m in managers})==1
 assert s.focus_recovery.attempts==1 and s.stop_reason=='focus_lost'

def test_next_round_initial_focus_cannot_bypass_budget(state,monkeypatch):
 from jump_rope_bot import JumpRopeBot
 m=state.make();m.initial_focus_done=True;m.attempts=1
 bot=JumpRopeBot(focus_recovery=m);monkeypatch.setattr(bot,'find_game',lambda:1)
 assert bot.focus_game() is None and not state.calls and bot.stop_reason=='focus_lost'

@pytest.mark.parametrize('during_capture',[False,True])
def test_full_loop_rebuilds_capture_and_only_uses_new_frame(state,monkeypatch,during_capture):
 import jump_rope_bot as b
 import numpy as np
 state.fg=1 if during_capture else 2
 events=[];made=[]
 class Capture:
  def __init__(self,*a,**kw):self.n=len(made)+1;made.append(self);events.append(('new',self.n))
  def grab(self):
   events.append(('grab',self.n))
   if self.n==1:
    assert during_capture
    state.fg=2;raise b.FocusLostError('lost during grab')
   return np.zeros((540,960,3),np.uint8)
  def close(self):events.append(('close',self.n))
 class Gate:
  finished=False
  @staticmethod
  def reset_cache():pass
  def observe(self,frame):self.finished=True;return False
 m=state.make();bot=b.JumpRopeBot(b.BotConfig(diagnostics_enabled=False),focus_recovery=m,
   detector=SimpleNamespace(backend='onnx-directml'),
   pulse_factory=lambda *a:SimpleNamespace(error=None,reset=lambda reason:None,close=lambda:None))
 bot._hwnd=1;bot.gate_type=Gate;monkeypatch.setattr(bot,'focus_game',lambda:1)
 monkeypatch.setattr(b,'GameCapture',Capture)
 bot.run()
 assert bot.stop_reason=='round_finished' and len(made)==2
 assert events.index(('close',1))<events.index(('new',2))<events.index(('grab',2))
 assert m.attempts==m.successes==1 and bot.frame_id==1
