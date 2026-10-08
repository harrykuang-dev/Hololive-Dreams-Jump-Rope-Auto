"""Automatic jump-rope player for the hololive-Dreams Windows game."""

from __future__ import annotations

import argparse
import ctypes
import logging
import threading
import time
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import win32api
import win32con
import win32gui
import win32process

from vision import GameCapture, RoundGate, StartupNavigator, StartupScreen, TemporaryCaptureOverlayError, NoFreshFrameError, RecoveredFrameGap
from v27_detector import VisualPassDetector

LOG = logging.getLogger("jump-rope-auto")


class GameNotFoundError(RuntimeError):
    """Raised when the game window cannot be found."""


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

    def validate(self) -> None:
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


class JumpRopeBot:
    """Single-round visual controller; never advances menus or retries a round."""

    def __init__(self, config: BotConfig | None = None, *,
                 clock: Callable[[], float] = time.perf_counter,
                 sleeper: Callable[[float], None] = time.sleep,
                 stop_requested: Callable[[], bool] | None = None) -> None:
        self.config = config or BotConfig()
        self.config.validate()
        self._clock = clock
        self._sleep = sleeper
        self._stop = threading.Event()
        self._external_stop = stop_requested or (lambda: False)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd: int | None = None
        self.tap_count = 0
        self.candidate_count = 0
        self.last_error: Exception | None = None
        self.last_detector_score = 0.0
        self.stop_reason = "not_started"
        self.last_tap_at: float | None = None
        self.round_started_at: float | None = None
        self.input_times: list[float] = []
        self.menu_actions: list[tuple[str, float]] = []
        self.recording_performance = None
        self.diagnostic_recorder = None
        self._mouse_down = False
        self.gate_type = RoundGate
        if self.config.shared_normalization:
            from shared_gate import SharedRoundGate
            SharedRoundGate.reset_cache()
            self.gate_type = SharedRoundGate
        self.input_pulses = []
        self.basic_performance = {}

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def _stopped(self) -> bool:
        return self._stop.is_set() or self._external_stop()

    def find_game(self) -> int:
        hwnd = win32gui.FindWindow(self.config.window_class, self.config.window_title)
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise GameNotFoundError(
                f'找不到遊戲視窗 "{self.config.window_title}"。請先開啟遊戲且不要最小化。'
            )
        return hwnd

    @staticmethod
    def _allow_foreground_switch() -> None:
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except (AttributeError, OSError):
            pass

    def focus_game(self) -> int:
        hwnd = self.find_game()
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            self._sleep(0.15)
        self._allow_foreground_switch()
        foreground = win32gui.GetForegroundWindow()
        current_thread = win32api.GetCurrentThreadId()
        target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
        foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground)
        attached: list[int] = []
        try:
            for thread_id in {target_thread, foreground_thread} - {current_thread}:
                win32process.AttachThreadInput(current_thread, thread_id, True)
                attached.append(thread_id)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetFocus(hwnd)
        except Exception as error:
            raise RuntimeError("無法將遊戲切到前景；請手動點一下遊戲視窗後重試。") from error
        finally:
            for thread_id in attached:
                win32process.AttachThreadInput(current_thread, thread_id, False)
        self._hwnd = hwnd
        return hwnd

    def tap_jump(self, frame) -> bool:
        """Click the game's own Jump button, which Unity accepts reliably."""
        if self.config.observe_only:
            return False
        if not self._hwnd:
            raise GameNotFoundError("遊戲視窗已關閉。")
        if self._stopped() or win32gui.GetForegroundWindow() != self._hwnd:
            self.stop()
            return False
        if not self.gate_type.gameplay_visible(frame) or not self.gate_type.player_ready(frame):
            self.stop()
            return False
        point = self.gate_type.jump_position(frame)
        if point is None:
            self.stop()
            return False
        left, top, right, bottom = win32gui.GetClientRect(self._hwnd)
        client_x = round((right - left) * point[0])
        client_y = round((bottom - top) * point[1])
        screen_x, screen_y = win32gui.ClientToScreen(self._hwnd, (client_x, client_y))
        win32api.SetCursorPos((screen_x, screen_y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        self._mouse_down = True
        self.last_tap_at = self._clock()
        self.input_times.append(self.last_tap_at)
        try:
            self._sleep(self.config.key_down_time)
        finally:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
            released_at = self._clock()
            self.input_pulses.append({'down':self.last_tap_at,'up':released_at,
                'requested_ms':self.config.key_down_time*1000,
                'actual_ms':(released_at-self.last_tap_at)*1000})
            self._mouse_down = False
        return True

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
        if win32gui.GetForegroundWindow() != self._hwnd:
            self.stop_reason = 'focus_lost'
            return False
        return True

    def _loop(self) -> None:
        self._running.set()
        self.tap_count = 0
        self.candidate_count = 0
        self.last_error = None
        self.stop_reason = "stopped"
        self.last_tap_at = None
        self.input_pulses = []
        self.round_started_at = None
        self.input_times = []
        self.menu_actions = []
        self.recording_performance = None
        self._mouse_down = False
        recorder = None
        postroll_done = False
        sample_times = []
        numeric = {k:[] for k in ('capture_ms','gate_ms','detector_ms','fresh_capture_ms','input_delay_ms','record_submit_ms','iteration_ms','sleep_requested_ms','sleep_actual_ms')}
        try:
            if self._stopped():
                return
            self.focus_game()
            detector = VisualPassDetector()
            gate = self.gate_type()
            startup_screen = StartupScreen() if self.config.auto_start and not self.config.observe_only else None
            navigator = StartupNavigator(startup_screen) if startup_screen is not None else None
            capture = (GameCapture(self._hwnd) if self.config.capture_backend == 'screen'
                       else GameCapture(self._hwnd, backend=self.config.capture_backend))
            LOG.info('擷取後端：%s；目標 %.0f FPS', self.config.capture_backend, self.config.target_fps)
            started = self._clock()
            last_report = started
            captured_once = False
            gameplay_seen = False
            first_hud_at = None
            rope_evidence_seen = False
            while not self._stopped():
                loop_started = self._clock()
                if recorder is not None:
                    recorder.check_health()
                if win32gui.GetForegroundWindow() != self._hwnd:
                    LOG.info("遊戲失去焦點，停止輸入")
                    self.stop_reason = "focus_lost"
                    break
                try:
                    frame = capture.grab()
                except RecoveredFrameGap:
                    # No cached pixels or pre-gap candidate can survive recovery.
                    # Original input cooldown, configured stop, focus and visibility guards remain.
                    detector = VisualPassDetector()
                    LOG.warning('DXGI 短暫空檔已恢復，重建識別狀態；本次不輸入')
                    continue
                except TemporaryCaptureOverlayError:
                    # The launch action's banner/cursor can outlive startup.
                    # Before the FIRST pixel capture only, await its removal
                    # for at most 60s (and within the startup deadline). GUI
                    # clicks can leave the indicator up longer than launches.
                    # No frame or input is authorized under it.
                    # A banner during gameplay still immediately stops the bot.
                    if captured_once or self._clock()-started >= min(60, self.config.startup_timeout):
                        raise
                    self._sleep(.05)
                    continue
                except NoFreshFrameError:
                    # The first HUD can precede the animated rope. Allow at
                    # most 3s of initial static countdown, before ANY reliable
                    # rope or candidate/input. No cached frame is processed.
                    # Once tracking begins, a missing new frame still stops.
                    countdown_wait = (first_hud_at is not None
                        and self._clock()-first_hud_at < 3
                        and not rope_evidence_seen and self.candidate_count == 0
                        and self.tap_count == 0)
                    if ((gameplay_seen and not countdown_wait)
                            or not self.config.wait_for_round):
                        raise
                    if self._clock()-started >= self.config.startup_timeout:
                        self.stop_reason = 'startup_timeout'
                        break
                    continue
                captured_once = True
                now = self._clock()
                timing = {'capture_ms': round((now-loop_started)*1000, 3)}
                if self.config.record_path is not None and recorder is None:
                    from diagnostics import RoundDiagnostics as EvidenceRecorder
                    recorder = EvidenceRecorder(self.config.record_path, frame,
                        fps=self.config.target_fps, defer_resize=self.config.defer_record_resize)
                    self.diagnostic_recorder = recorder
                gate_started = self._clock()
                allowed = gate.observe(frame)
                visible = self.gate_type.gameplay_visible(frame)
                if visible and first_hud_at is None:
                    first_hud_at = now
                gameplay_seen = gameplay_seen or visible
                # Even one live-HUD frame permanently disables startup clicks.
                # This covers a very short round that ends before the gate's
                # three-frame confirmation can latch.
                if navigator is not None and not navigator.finished and self.gate_type.gameplay_visible(frame):
                    navigator.seal()
                ready = self.gate_type.player_ready(frame) if allowed else False
                timing['gate_ms'] = round((self._clock()-gate_started)*1000, 3)
                candidate = False
                clicked = False
                measured = False
                fresh_hud = None
                fresh_ready = None
                if allowed and self.round_started_at is None:
                    self.round_started_at = now
                    if navigator is not None:
                        navigator.seal()
                    LOG.info("已確認單局遊玩畫面；開始%s", "只觀察" if self.config.observe_only else "視覺控制")
                phase = ("result" if gate.finished else
                         "round" if self.round_started_at is not None else "waiting")
                def record(observed_frame, at, *, hud, player_ready, event=False,
                           sent=False, input_elapsed=None, menu_action=None,
                           menu_input_elapsed=None):
                    if phase=='round':
                        sample_times.append(at-started)
                        for key in ('capture_ms','gate_ms','detector_ms','fresh_capture_ms','input_delay_ms'):
                            if key in timing:numeric[key].append(timing[key])
                    if recorder is None:
                        return
                    record_started=self._clock()
                    p = detector.position if measured else None
                    recorder.add(
                        observed_frame, at-started, hud=hud, ready=player_ready,
                        candidate=event, clicked=sent,
                        detector_score=detector.last_score,
                        input_elapsed=input_elapsed,
                        telemetry={
                            **timing,
                            'capture_backend': self.config.capture_backend,
                            **(getattr(detector, 'telemetry', lambda: {})() if measured else {}),
                            "phase": phase,
                            "rope_height": round(p.sag+p.offset, 4) if p else None,
                            "rope_coverage": round(p.coverage, 4) if p else None,
                            "rope_color": p.color if p else None,
                            "rope_contrast": round(p.contrast, 4) if p else None,
                            "fresh_hud": fresh_hud,
                            "fresh_ready": fresh_ready,
                            "menu_action": menu_action,
                            "menu_input_t": round(menu_input_elapsed, 4)
                            if menu_input_elapsed is not None else None,
                        },
                    )
                    if phase=='round':numeric['record_submit_ms'].append((self._clock()-record_started)*1000)
                if gate.finished:
                    if navigator is not None:
                        navigator.seal()
                    LOG.info("本局結束或畫面無法確認，已停止；不會點擊下一步")
                    self.stop_reason = "round_finished"
                    record(frame, now, hud=False, player_ready=False)
                    postroll_until = self._clock() + self.config.result_postroll
                    while self._clock() < postroll_until and self._result_tail_allowed():
                        self._sleep(0.05)
                        try:
                            tail = capture.grab()
                        except NoFreshFrameError:
                            continue  # Result tail is bounded and sends no input.
                        record(tail, self._clock(), hud=False, player_ready=False)
                    postroll_done = True
                    break
                if self.round_started_at is None and self.config.wait_for_round:
                    if now-started >= self.config.startup_timeout:
                        self.stop_reason = "startup_timeout"
                        record(frame, now, hud=False, player_ready=False)
                        break
                if self.round_started_at is None and navigator is not None:
                    action = navigator.observe(frame)
                    if action is not None:
                        try:
                            fresh = capture.grab()
                        except NoFreshFrameError:
                            continue  # No fresh pixels means no menu click.
                        if startup_screen.identify(fresh) == action and self.tap_startup(
                                action, fresh, startup_screen):
                            navigator.mark_clicked(action)
                            LOG.info("啟動前已辨識並點擊 %s；本局結束後不會再操作選單", action)
                            record(frame, now, hud=False, player_ready=False,
                                   menu_action=action,
                                   menu_input_elapsed=self.menu_actions[-1][1]-started)
                            continue
                if (self.round_started_at is not None
                        and self.config.round_timeout is not None
                        and now-self.round_started_at >= self.config.round_timeout):
                    self.stop_reason = "round_timeout"
                    record(frame, now, hud=allowed, player_ready=ready)
                    break
                if not allowed or not ready:
                    record(frame, now, hud=allowed, player_ready=ready)
                    sleep_started=self._clock()
                    if phase=='round':numeric['iteration_ms'].append((sleep_started-loop_started)*1000)
                    self._sleep(0.02)
                    if phase=='round':
                        numeric['sleep_requested_ms'].append(20.)
                        numeric['sleep_actual_ms'].append((self._clock()-sleep_started)*1000)
                    continue
                detector_started = self._clock()
                candidate = detector.observe(frame, now)
                rope_evidence_seen = (rope_evidence_seen
                                      or getattr(detector.position, 'coverage', 0) >= .35)
                timing['detector_ms'] = round((self._clock()-detector_started)*1000, 3)
                measured = True
                if candidate:
                    self.candidate_count += 1
                    if not self.config.observe_only:
                        if recorder is not None:
                            recorder.check_health()
                        fresh_started = self._clock()
                        try:
                            fresh = capture.grab()
                        except RecoveredFrameGap:
                            record(frame, now, hud=allowed, player_ready=ready,
                                   event=candidate, sent=False)
                            detector = VisualPassDetector()
                            LOG.warning('按鍵前擷取有空檔；取消候選並重建識別狀態')
                            continue
                        timing['fresh_capture_ms'] = round((self._clock()-fresh_started)*1000, 3)
                        fresh_hud = gate.observe(fresh)
                        fresh_ready = self.gate_type.player_ready(fresh) if fresh_hud else False
                        if not fresh_hud:
                            self.stop_reason = "round_finished"
                            phase = "result"
                            record(fresh, self._clock(), hud=False, player_ready=False)
                            break
                        if fresh_ready and self.tap_jump(fresh):
                            self.tap_count += 1
                            clicked = True
                            timing['input_delay_ms'] = round((self.last_tap_at-now)*1000, 3)
                self.last_detector_score = detector.last_score
                record(frame, now, hud=allowed, player_ready=ready,
                       event=candidate, sent=clicked,
                       input_elapsed=(self.last_tap_at-started)
                       if clicked and self.last_tap_at is not None else None)
                if now-last_report >= 5:
                    LOG.info("候選=%d，已送出輸入=%d；此數字不是遊戲分數",
                             self.candidate_count, self.tap_count)
                    last_report = now
                # Budget the entire iteration, not an extra sleep after work.
                # This schedules observations only; it never schedules jumps.
                elapsed_iteration=self._clock()-loop_started
                numeric['iteration_ms'].append(elapsed_iteration*1000)
                remaining = 1/self.config.target_fps-elapsed_iteration
                if remaining > 0:
                    sleep_started=self._clock()
                    self._sleep(remaining)
                    numeric['sleep_requested_ms'].append(remaining*1000)
                    numeric['sleep_actual_ms'].append((self._clock()-sleep_started)*1000)
        except Exception as error:
            self.last_error = error
            self.stop_reason = "error"
            LOG.exception("自動跳繩已停止")
        finally:
            if self._mouse_down:
                try:
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
                    self._mouse_down = False
                except Exception as error:
                    LOG.warning("無法確認滑鼠按鍵已釋放：%s", error)
            if (self.stop_reason == "round_finished" and not postroll_done
                    and recorder is not None and 'capture' in locals()):
                try:
                    postroll_until = self._clock() + self.config.result_postroll
                    while self._clock() < postroll_until and self._result_tail_allowed():
                        self._sleep(0.05)
                        tail = capture.grab()
                        recorder.add(tail, self._clock()-started, hud=False, ready=False,
                                     candidate=False, clicked=False,
                                     detector_score=detector.last_score,
                                     telemetry={"phase": "result", "rope_height": None,
                                                "rope_coverage": None, "rope_color": None,
                                                "rope_contrast": None, "fresh_hud": None,
                                                "fresh_ready": None})
                except Exception as error:
                    LOG.warning("結算後錄影尾段未完成：%s", error)
                    self.stop_reason = 'recording_error'
                    if self.last_error is None:
                        self.last_error = error
            if recorder:
                try:
                    recorder.close(stop_reason=self.stop_reason,
                                   tap_count=self.tap_count,
                                   candidate_count=self.candidate_count,
                                   error=str(self.last_error) if self.last_error else None,
                                   round_started_t=(self.round_started_at-started)
                                   if self.round_started_at is not None else None,
                                   input_times=[round(t-started, 4) for t in self.input_times],
                                   menu_actions=[{"action": action, "t": round(t-started, 4)}
                                                 for action, t in self.menu_actions])
                    self.recording_performance = getattr(recorder, 'performance', None)
                except Exception as error:
                    LOG.exception("無法完成錄影紀錄")
                    self.stop_reason = 'recording_error'
                    if self.last_error is None:
                        self.last_error = error
            if 'capture' in locals():
                try:
                    getattr(capture, 'close', lambda: None)()
                except Exception as error:
                    self.stop_reason = 'capture_close_error'
                    self.last_error = self.last_error or error
            duration=sample_times[-1]-sample_times[0] if len(sample_times)>1 else 0
            self.basic_performance={'actual_round_fps':(len(sample_times)-1)/duration if duration else None,
                'capture_events':[{**event,'time':round(event['time']-started,4)}
                    for event in getattr(getattr(capture,'impl',None),'capture_events',[])] if 'capture' in locals() else [],
                'fresh_detection_fps':len(numeric['detector_ms'])/duration if duration else None,
                'round_frames':len(sample_times),'tap_count':self.tap_count,
                'diagnostics_enabled':self.config.diagnostics_enabled,
                'measurements':{k:{'median':statistics.median(values),
                    'p95':sorted(values)[min(len(values)-1,int(.95*(len(values)-1)))],
                    'count':len(values)} for k,values in numeric.items() if values},
                'pulses':{'count':len(self.input_pulses),
                    'median_ms':statistics.median(p['actual_ms'] for p in self.input_pulses) if self.input_pulses else None,
                    'minimum_ms':min((p['actual_ms'] for p in self.input_pulses),default=None),
                    'maximum_ms':max((p['actual_ms'] for p in self.input_pulses),default=None)}}
            if self.config.shared_normalization:self.gate_type.reset_cache()
            self._running.clear()

    def run(self, duration: float | None = None) -> None:
        if duration is not None and duration <= 0:
            raise ValueError("duration must be positive")
        self._stop.clear()
        if duration is None:
            self._loop()
            if self.last_error:
                raise self.last_error
            return
        timer = threading.Timer(duration, self.stop)
        timer.daemon = True
        timer.start()
        try:
            self._loop()
            if self.last_error:
                raise self.last_error
        finally:
            timer.cancel()

    def start(self) -> None:
        if self.running or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="jump-rope-bot")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hololive Dreams 跳繩自動遊玩程式")
    parser.add_argument("--duration", type=float, help="測試秒數；省略則持續執行")
    parser.add_argument("--observe", action="store_true", help="只觀察繩子，不送出輸入")
    parser.add_argument("--record", type=Path, help="儲存本局影片及逐幀輸入紀錄（MP4）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bot = JumpRopeBot(BotConfig(observe_only=args.observe, record_path=args.record))
    try:
        print("只觀察，不輸入" if args.observe else "開始單局視覺跳繩（尚未驗證100下）")
        print("按 Ctrl+C 停止。")
        bot.run(args.duration)
    except KeyboardInterrupt:
        bot.stop()
    except (GameNotFoundError, RuntimeError, ValueError) as error:
        print(f"錯誤：{error}")
        return 1
    finally:
        print(f"已停止，共送出 {bot.tap_count} 次跳躍輸入；原因：{bot.stop_reason}。")
        if args.record:
            print(f"本局錄影：{args.record}；逐幀紀錄：{args.record.with_suffix('.events.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
