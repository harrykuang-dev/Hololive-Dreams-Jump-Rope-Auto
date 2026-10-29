"""Window access, menu input and cancellable controller lifecycle."""
from __future__ import annotations
import ctypes,logging,threading,time
from dataclasses import dataclass
from pathlib import Path
import win32api,win32con,win32gui
from vision import RoundGate,StartupScreen
from timing_control import DEFAULT_TIMING_POSITION,validate_timing_position
LOG=logging.getLogger('jump-rope-auto')
class GameNotFoundError(RuntimeError):pass
@dataclass(frozen=True)
class BotConfig:
    window_title: str = "hololive-Dreams"
    window_class: str = "UnityWndClass"
    key_down_time: float = 0.025
    observe_only: bool = False
    record_path: Path | None = None
    wait_for_round: bool = False
    startup_timeout: float = 120.0
    round_timeout: float | None = None
    result_postroll: float = 1.0
    auto_start: bool = False
    target_fps: float = 60.0
    capture_backend: str = 'screen'
    shared_normalization: bool = False
    diagnostics_enabled: bool = True
    defer_record_resize: bool = False
    timing_position: float = DEFAULT_TIMING_POSITION
    score_limit: int | None = None

    def validate(self) -> None:
        validate_timing_position(self.timing_position)
        if self.score_limit is not None and (type(self.score_limit) is not int or not 1<=self.score_limit<=999):
            raise ValueError('Score limit must be an integer from 1 to 999 or None')
        if not 0.001 <= self.key_down_time <= 0.05:
            raise ValueError("key_down_time must be between 0.001 and 0.05 seconds")
        if self.record_path is not None and self.record_path.suffix.lower() != ".mp4":
            raise ValueError("record_path must end in .mp4")
        if self.startup_timeout <= 0:
            raise ValueError("startup_timeout must be positive")
        if self.round_timeout is not None and self.round_timeout <= 0:
            raise ValueError("round_timeout must be positive")
        if not 0 <= self.result_postroll <= 5:
            raise ValueError("result_postroll must be between 0 and 5 seconds")
        if not 15 <= self.target_fps <= 60:
            raise ValueError('target_fps must be between 15 and 60')
        if self.capture_backend not in ('screen', 'printwindow', 'dxgi'):
            raise ValueError('capture_backend must be screen, printwindow or dxgi')
        if not self.diagnostics_enabled and self.record_path is not None:
            raise ValueError('Diagnostics disabled requires record_path=None')

class WindowController:
    def __init__(self, config=None, *, clock=time.perf_counter, sleeper=time.sleep, stop_requested=None,
                 focus_recovery=None):
        self.config=config or BotConfig();self.config.validate()
        self._clock,self._sleep=clock,sleeper
        self._stop=threading.Event();self._external_stop=stop_requested or (lambda:False)
        self._running=threading.Event();self._thread=None;self._hwnd=None
        self.tap_count=self.candidate_count=0;self.last_error=None;self.stop_reason='not_started'
        self.last_tap_at=self.round_started_at=None
        self.input_times=[];self.menu_actions=[];self.input_pulses=[]
        self.recording_performance=self.diagnostic_recorder=None;self.basic_performance={}
        self._mouse_down=False;self.gate_type=RoundGate
        from focus_recovery import FocusRecovery
        self.focus_recovery=focus_recovery or FocusRecovery(diagnostics=self.config.diagnostics_enabled,
                                                           clock=clock,sleeper=sleeper)
        self._capture_restart=False

    def ensure_foreground(self):
        before=self.focus_recovery.successes
        def release():
            reset=getattr(self,'reset_evidence',None)
            if reset:reset('focus_lost')
            if self._mouse_down:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,0,0)
                self._mouse_down=False
        ready=self.focus_recovery.ensure(self._hwnd,stopped=self._stopped,release=release)
        if self.focus_recovery.successes!=before:
            self._capture_restart=True
            self.gate_type.reset_cache()
        return ready

    @property
    def running(self) -> bool:
            return self._running.is_set()

    def _stopped(self) -> bool:
            return self._stop.is_set() or self._external_stop()

    def find_game(self) -> int:
            hwnd = win32gui.FindWindow(self.config.window_class, self.config.window_title)
            if not hwnd or not win32gui.IsWindow(hwnd):
                raise GameNotFoundError(
                    f'找不到遊戲視窗 "{self.config.window_title}"。請先開啟遊戲。'
                )
            return hwnd

    @staticmethod
    def _allow_foreground_switch() -> None:
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except (AttributeError, OSError):
                pass

    def focus_game(self) -> int | None:
            hwnd = self.find_game()
            if self.focus_recovery.initial_focus_done:
                self._hwnd=hwnd
                if self.ensure_foreground():return hwnd
                self.stop_reason='stopped' if self._stopped() else 'focus_lost'
                return None
            if self.focus_recovery.diagnostics:
                from focus_recovery import window_snapshot
                self.focus_recovery.note('initial_focus_begin',target=window_snapshot(hwnd),
                    foreground=window_snapshot(win32gui.GetForegroundWindow()))
            if win32gui.IsIconic(hwnd):
                LOG.info('正在還原遊戲視窗')
                # Never synchronously message a minimized Unity window or join its
                # input queue to Tk's queue. The UI must remain free to cancel.
                ctypes.windll.user32.ShowWindowAsync(ctypes.c_void_p(hwnd), win32con.SW_RESTORE)
            self._allow_foreground_switch()
            deadline = self._clock()+3.0
            stable_since = None
            while self._clock() < deadline:
                if self._stopped():
                    return None
                if not win32gui.IsWindow(hwnd):
                    raise GameNotFoundError('遊戲視窗已關閉。')
                if not win32gui.IsIconic(hwnd):
                    if win32gui.GetForegroundWindow() != hwnd:
                        try:
                            win32gui.SetForegroundWindow(hwnd)
                        except Exception:
                            # Windows may temporarily deny focus during restoration.
                            # Retry for a bounded interval without blocking the UI.
                            pass
                    _,_,width,height = win32gui.GetClientRect(hwnd)
                    ready = win32gui.GetForegroundWindow() == hwnd and width > 0 and height > 0
                    if ready:
                        stable_since = self._clock() if stable_since is None else stable_since
                        if self._clock()-stable_since >= .15:
                            self._hwnd = hwnd
                            self.focus_recovery.initial_focus_done=True
                            self.focus_recovery.note('initial_focus_ready',target_hwnd=hwnd)
                            return hwnd
                    else:
                        stable_since = None
                else:
                    stable_since = None
                self._sleep(.05)
            raise RuntimeError('無法還原遊戲或切到前景；請手動還原遊戲視窗後重試。')

    def tap_startup(self, action: str, frame, screen: StartupScreen) -> bool:
            """One pre-round menu click; this path is disabled after round entry."""
            if (self.config.observe_only or not self.config.auto_start
                    or self.round_started_at is not None or self._stopped()
                    or not self._hwnd or win32gui.GetForegroundWindow() != self._hwnd
                    or screen.identify(frame) != action):
                return False
            x, y = StartupScreen.BUTTONS[action]
            left, top, right, bottom = win32gui.GetClientRect(self._hwnd)
            client = (round((right-left)*x), round((bottom-top)*y))
            win32api.SetCursorPos(win32gui.ClientToScreen(self._hwnd, client))
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
            self._mouse_down = True
            self.menu_actions.append((action, self._clock()))
            try:
                # Menu UI polling is independent of the short, visual-timed jump tap.
                # Hold across several Unity frames so a newly opened page receives it.
                self._sleep(0.12)
            finally:
                win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
                self._mouse_down = False
            return True

    def _result_tail_allowed(self) -> bool:
            # A stop during the non-input recording tail must also cancel the
            # batch runner's permission to open the next round.
            if self._stopped():
                self.stop_reason = 'stopped'
                return False
            if not self.ensure_foreground():
                self.stop_reason = 'stopped' if self._stopped() else 'focus_lost'
                return False
            return True

    def run(self,duration=None):
        if duration is not None and duration<=0:raise ValueError('duration must be positive')
        timer=threading.Timer(duration,self.stop) if duration is not None else None
        if timer:timer.daemon=True;timer.start()
        try:
            self._loop()
            if self.last_error:raise self.last_error
        finally:
            if timer:timer.cancel()
    def start(self):
        if self.running or self._thread and self._thread.is_alive():return
        self._thread=threading.Thread(target=self._loop,daemon=True,name='jump-rope-bot');self._thread.start()
    def stop(self):self._stop.set()
    def join(self,timeout=None):
        if self._thread:self._thread.join(timeout)
