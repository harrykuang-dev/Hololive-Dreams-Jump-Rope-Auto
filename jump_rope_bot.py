"""Full-frame event prediction and nonblocking 25ms jump input."""
from collections import deque
from dataclasses import asdict
import ctypes,logging,threading,time
import cv2
import win32api,win32con,win32gui
from window_control import BotConfig,WindowController,GameNotFoundError
from vision import GameCapture,StartupScreen,StartupNavigator,NoFreshFrameError,RecoveredFrameGap,FocusLostError
from shared_gate import EventRoundGate
from timing_control import control_config
from controller.policy import ArcCarryPolicy
from input_timer import TimedPulse,InputRejected
LOG=logging.getLogger('jump-rope-auto')

def visible_hearts(crop):
    import numpy as np
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV);green=cv2.inRange(hsv,(35,100,130),(85,255,255))
    active=[int(np.count_nonzero(green[:,x:x+22])>=60) for x in (16,41,65)]
    inactive=[int(np.mean(cv2.inRange(hsv[15:29,x-5:x+6],(108,55,30),(140,190,135))>0)>.55) for x in (27,52,76)]
    return sum(active) if all(a or b for a,b in zip(active,inactive)) else None

class JumpRopeBot(WindowController):
    def __init__(self,config=None,*,detector=None,pulse_factory=TimedPulse,score_notify=lambda _score:None,
                 diagnostic_session=None,diagnostic_round=1,**kwargs):
        super().__init__(config,**kwargs)
        self.detector=detector;self.control=ArcCarryPolicy('jump-rope',control_config(
            self.config.timing_position,backend=getattr(detector,'backend',None)))
        self.pulse_factory=pulse_factory;self.pulse=None
        self.gate_type=type('SessionGate',(EventRoundGate,),{})
        self.frame_id=0;self._last_hearts=None
        self.score_notify=score_notify;self.score_limit_reached=False;self.confirmed_score=None
        self.diagnostic_session=diagnostic_session;self.diagnostic_round=diagnostic_round
    def _stopped(self):
        if self.pulse and self.pulse.error:raise RuntimeError('Input release failed') from self.pulse.error
        return super()._stopped()
    def stop(self):
        super().stop()
        if self.pulse:self.pulse.reset('stop')
    def reset_evidence(self,reason):
        if self.pulse:self.pulse.reset(reason)
        if reason=='heart_loss':self.control.mark_loss(time.perf_counter_ns())
        elif reason in ('capture_recovered','no_fresh_frame'):self.control.invalidate_observation()
        else:self.control.reset()
    def _native(self,command,context,reason=None):
        if command=='down':
            if self.diagnostic_recorder:self.diagnostic_recorder.check_health()
            if self._stopped() or win32gui.GetForegroundWindow()!=self._hwnd:raise InputRejected('focus_or_stop_before_down')
            r=win32gui.GetClientRect(self._hwnd)
            if (r[2]-r[0],r[3]-r[1])!=context['source_size']:raise InputRejected('resize_before_down')
            if context['frame_id']!=self.frame_id:raise InputRejected('expired_or_superseded_frame')
            # The default has no fixed frame-age cutoff. Explicit bounded
            # decisions still expire; latest-frame and focus checks always run.
            # Native return is not the game's observable delivery timestamp.
            called=time.perf_counter_ns()
            if context['expires_ns'] is not None and called>context['expires_ns']:raise InputRejected('expired_or_superseded_frame')
            context['native_down_begin_ns']=called
        else:context['native_up_begin_ns']=time.perf_counter_ns()
        flag=win32con.MOUSEEVENTF_LEFTDOWN if command=='down' else win32con.MOUSEEVENTF_LEFTUP
        win32api.mouse_event(flag,0,0);returned=time.perf_counter_ns()
        if command=='down':
            context['down_ns']=returned;self.control.commit_jump(returned)
            self.last_tap_at=returned/1e9;self.input_times.append(self.last_tap_at)
        elif context.get('down_ns') is not None:
            self.input_pulses.append(dict(down=context['down_ns']/1e9,up=returned/1e9,requested_ms=25,
                actual_ms=(returned-context['down_ns'])/1e6,frame_id=context['frame_id'],release_reason=reason,
                  native_down_call_ms=(context['down_ns']-context.get('native_down_begin_ns',context['down_ns']))/1e6,
                  native_up_call_ms=(returned-context['native_up_begin_ns'])/1e6,
                capture_return_to_down_ms=(context['down_ns']-context['capture_ns'])/1e6))
        if self.diagnostic_recorder:
            self.diagnostic_recorder.input_event(command,context,returned,reason)
        return returned
    def tap_jump(self,frame,decision=None,stamp=None):
        if decision is None or not decision.jump or not decision.ready or self.config.observe_only or self._stopped():return False
        if not self.gate_type.gameplay_visible(frame):self.reset_evidence('hud_changed');return False
        point=self.gate_type.jump_position(frame)
        if point is None:raise RuntimeError('Jump button not found in current frame')
        h,w=frame.shape[:2];screen_point=win32gui.ClientToScreen(self._hwnd,(round(w*point[0]),round(h*point[1])))
        if win32api.GetCursorPos()!=screen_point:win32api.SetCursorPos(screen_point)
        context=dict(frame_id=self.frame_id,source_size=(w,h),expires_ns=decision.valid_until_ns,capture_ns=stamp,down_ns=None)
        return self.pulse.press(context,valid_until_ns=decision.valid_until_ns)
    def _loop(self):
        self._running.set();self.stop_reason='stopped';capture=None;timings=deque(maxlen=10000);recorder=None
        try:
            if self._stopped():return
            if self.focus_game() is None or self._stopped():return
            if self.detector is None:
                from detector import FullFrameDetector
                self.detector=FullFrameDetector(stopped=self._stopped)
                self.control=ArcCarryPolicy('jump-rope',control_config(
                    self.config.timing_position,backend=self.detector.backend))
            if self._stopped():return
            self.gate_type.reset_cache();gate=self.gate_type();screen=StartupScreen();navigator=StartupNavigator(screen)
            self.focus_recovery.note('capture_initialization_begin',target_hwnd=self._hwnd)
            capture=GameCapture(self._hwnd,backend=self.config.capture_backend,stop_requested=self._stopped)
            if self.config.diagnostics_enabled:
                camera=getattr(getattr(capture,'impl',None),'camera',None)
                details={key:getattr(camera,key,None) for key in ('width','height','device_idx','output_idx')}
                self.focus_recovery.note('capture_initialization_ready',target_hwnd=self._hwnd,
                    backend=self.config.capture_backend,camera=details)
            self.pulse=self.pulse_factory(lambda c:self._native('down',c),lambda c,r:self._native('up',c,r))
            score_guard=None
            if self.config.score_limit is not None:
                from score_limit import ScoreLimit
                score_guard=ScoreLimit(self.config.score_limit)
            began=time.perf_counter_ns();rope_seen=False;source_size=None
            while not self._stopped():
                iteration=time.perf_counter_ns()
                if recorder:recorder.check_health()
                if not self.ensure_foreground():
                    self.stop_reason='stopped' if self._stopped() else 'focus_lost';break
                if self._capture_restart:
                    capture.close()
                    capture=GameCapture(self._hwnd,backend=self.config.capture_backend,stop_requested=self._stopped)
                    self._capture_restart=False
                    self.focus_recovery.note('capture_reinitialized_after_focus')
                    continue
                capture_begin=time.perf_counter_ns()
                try:frame=capture.grab()
                except FocusLostError:
                    if not self.ensure_foreground():
                        self.stop_reason='stopped' if self._stopped() else 'focus_lost';break
                    continue
                except RecoveredFrameGap:
                    self.focus_recovery.note('capture_gap_recovered',round=self.diagnostic_round)
                    self.reset_evidence('capture_recovered');continue
                except NoFreshFrameError:
                    self.reset_evidence('no_fresh_frame')
                    if self.round_started_at is not None and (rope_seen or self.tap_count>0 or time.perf_counter()-self.round_started_at>=3):raise
                    if (time.perf_counter_ns()-began)/1e9>self.config.startup_timeout:self.stop_reason='startup_timeout';break
                    continue
                stamp=time.perf_counter_ns();self.frame_id+=1
                if self.frame_id==1:self.focus_recovery.note('first_frame',capture_ns=stamp,
                                                           source_size=list(frame.shape[1::-1]))
                if self._stopped():break
                if self.config.diagnostics_enabled and self.config.record_path and recorder is None:
                    from diagnostics import RoundDiagnostics
                    recorder=self.diagnostic_recorder=RoundDiagnostics(self.config.record_path,frame,
                        session=self.diagnostic_session,round_index=self.diagnostic_round)
                observed_size=(frame.shape[1],frame.shape[0])
                if source_size is not None and source_size!=observed_size:raise RuntimeError('Window resized; restart manually')
                source_size=observed_size;allowed=gate.observe(frame)
                if gate.finished:
                    self.stop_reason='round_finished';self.reset_evidence('round_finished')
                    if recorder:recorder.add(frame,(stamp-began)/1e9,hud=False,
                        telemetry=dict(phase='result',frame_id=self.frame_id,capture_ns=stamp))
                    break
                if self.gate_type.gameplay_visible(frame):navigator.seal()
                if not allowed:
                    self.reset_evidence('not_gameplay')
                    if recorder:
                        recorder.add(frame,(stamp-began)/1e9,hud=False,
                            telemetry=dict(phase='prepare',frame_id=self.frame_id,capture_ns=stamp,
                                source_size=list(frame.shape[1::-1]),screen=screen.identify(frame)))
                    if self.round_started_at is None and not navigator.finished:
                        action=navigator.observe(frame)
                        if action:
                            try:fresh=capture.grab()
                            except FocusLostError:continue
                            self.frame_id+=1
                            if recorder:
                                fresh_ns=time.perf_counter_ns()
                                recorder.add(fresh,(fresh_ns-began)/1e9,hud=False,
                                    telemetry=dict(phase='startup_recheck',frame_id=self.frame_id,
                                        capture_ns=fresh_ns,screen=screen.identify(fresh),menu_action=action))
                            if screen.identify(fresh)==action and self.tap_startup(action,fresh,screen):navigator.mark_clicked(action)
                    if (time.perf_counter_ns()-began)/1e9>self.config.startup_timeout:self.stop_reason='startup_timeout';break
                    self._sleep(.02);continue
                if self.round_started_at is None:self.round_started_at=stamp/1e9;navigator.seal()
                if self.config.round_timeout and time.perf_counter()-self.round_started_at>self.config.round_timeout:self.stop_reason='round_timeout';break
                h,w=frame.shape[:2]
                hearts=visible_hearts(cv2.resize(frame[round(190*h/540):round(235*h/540),round(55*w/960):round(155*w/960)],(100,45)))
                if hearts is not None:
                    if self._last_hearts is not None and hearts<self._last_hearts:self.reset_evidence('heart_loss')
                    self._last_hearts=hearts
                if score_guard:
                    reached=score_guard.observe(self.gate_type.normalized(frame),stamp)
                    self.confirmed_score=score_guard.score
                    if reached and not self.score_limit_reached:
                        self.reset_evidence('score_limit_reached');self.score_limit_reached=True
                        self.score_notify(self.confirmed_score)
                    if self.score_limit_reached:
                        if recorder:recorder.add(frame,(stamp-began)/1e9,hud=True,
                            telemetry=dict(phase='score_limit_wait',frame_id=self.frame_id,capture_ns=stamp,
                                confirmed_stop_score=self.confirmed_score,score_limit=self.config.score_limit,decision='score_limit_reached'))
                        self._sleep(.01);continue
                model_start=time.perf_counter_ns();prediction=self.detector.observe(frame,already_cropped=True);inferred=time.perf_counter_ns()
                decision=self.control.observe(prediction,stamp,frame.shape[:2],now_ns=time.perf_counter_ns())
                controlled=time.perf_counter_ns();rope_seen=rope_seen or prediction.rope_xyxy is not None;sent=False
                if decision.jump:
                    self.candidate_count+=1;sent=self.tap_jump(frame,decision,stamp)
                    if sent:self.tap_count+=1
                if recorder:
                    scale=[960/w,540/h,960/w,540/h]
                    scaled=lambda box:None if box is None else [a*b for a,b in zip(box,scale)]
                    recorder.add(frame,(stamp-began)/1e9,hud=True,ready=decision.ready,candidate=decision.jump,clicked=sent,
                        input_elapsed=(self.last_tap_at-began/1e9) if sent else None,
                        telemetry=dict(phase='round',frame_id=self.frame_id,capture_ns=stamp,presentation_ns=None,
                            policy=asdict(decision),decision=decision.reason,diagnostic=dict(self.control.last_diagnostic),
                            source_size=[w,h],capture_begin_ns=capture_begin,capture_ms=(stamp-capture_begin)/1e6,
                            model_timings_ms=getattr(prediction,'timings_ms',{}),
                            confirmed_score=self.confirmed_score,score_limit=self.config.score_limit,
                            rope_xyxy=scaled(prediction.rope_xyxy),marker_xyxy=scaled(prediction.marker_xyxy),
                            model_ms=(inferred-model_start)/1e6,control_ms=(controlled-inferred)/1e6,
                            capture_return_to_decision_ms=(controlled-stamp)/1e6))
                timings.append((time.perf_counter_ns()-iteration)/1e6)
                remaining=1/self.config.target_fps-(time.perf_counter_ns()-iteration)/1e9
                if remaining>0:self._sleep(remaining)
        except InterruptedError:self.stop_reason='stopped'
        except Exception as error:
            self.last_error=error;self.stop_reason='error';LOG.exception('自動跳繩已停止')
        finally:
            try:
                if self.pulse:self.pulse.close()
            except Exception as error:self.last_error=self.last_error or error;self.stop_reason='error'
            finally:
                try:
                    if capture:
                        capture.close()
                        self.focus_recovery.note('capture_closed',round=self.diagnostic_round,
                            events=getattr(getattr(capture,'impl',None),'capture_events',[]))
                except Exception as error:self.last_error=self.last_error or error;self.stop_reason='capture_close_error'
                try:
                    if recorder:recorder.close(stop_reason=self.stop_reason,tap_count=self.tap_count)
                except Exception as error:self.last_error=self.last_error or error;self.stop_reason='recording_error'
                self.basic_performance={'iteration_ms':list(timings)}
                self.gate_type.reset_cache();self._running.clear()
