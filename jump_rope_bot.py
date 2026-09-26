"""Automatic jump-rope player for the hololive-Dreams Windows game."""

from __future__ import annotations

import argparse
import ctypes
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import win32api
import win32con
import win32gui
import win32process

from vision import GameCapture, RoundGate
from rope_track import VisualPassDetector
from round_recording import RoundRecorder

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

    def validate(self) -> None:
        if not 0.001 <= self.key_down_time <= 0.05:
            raise ValueError("key_down_time must be between 0.001 and 0.05 seconds")
        if self.record_path is not None and self.record_path.suffix.lower() != ".mp4":
            raise ValueError("record_path must end in .mp4")


class JumpRopeBot:
    """Single-round visual controller; never advances menus or retries a round."""

    def __init__(self, config: BotConfig | None = None, *,
                 clock: Callable[[], float] = time.perf_counter,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.config = config or BotConfig()
        self.config.validate()
        self._clock = clock
        self._sleep = sleeper
        self._stop = threading.Event()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd: int | None = None
        self.tap_count = 0
        self.candidate_count = 0
        self.last_error: Exception | None = None
        self.last_detector_score = 0.0
        self.stop_reason = "not_started"
        self.last_tap_at: float | None = None

    @property
    def running(self) -> bool:
        return self._running.is_set()

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
        if self._stop.is_set() or win32gui.GetForegroundWindow() != self._hwnd:
            self.stop()
            return False
        if not RoundGate.gameplay_visible(frame) or not RoundGate.player_ready(frame):
            self.stop()
            return False
        point = RoundGate.jump_position(frame)
        if point is None:
            self.stop()
            return False
        left, top, right, bottom = win32gui.GetClientRect(self._hwnd)
        client_x = round((right - left) * point[0])
        client_y = round((bottom - top) * point[1])
        screen_x, screen_y = win32gui.ClientToScreen(self._hwnd, (client_x, client_y))
        win32api.SetCursorPos((screen_x, screen_y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        self.last_tap_at = self._clock()
        try:
            self._sleep(self.config.key_down_time)
        finally:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        return True

    def _loop(self) -> None:
        self._running.set()
        self.tap_count = 0
        self.candidate_count = 0
        self.last_error = None
        self.stop_reason = "stopped"
        self.last_tap_at = None
        recorder: RoundRecorder | None = None
        try:
            self.focus_game()
            detector = VisualPassDetector()
            gate = RoundGate()
            capture = GameCapture(self._hwnd)
            started = self._clock()
            while not self._stop.is_set():
                if win32api.GetAsyncKeyState(win32con.VK_F9) & 0x8000:
                    self.stop_reason = "F9"
                    break
                if win32gui.GetForegroundWindow() != self._hwnd:
                    LOG.info("遊戲失去焦點，停止輸入")
                    self.stop_reason = "focus_lost"
                    break
                frame = capture.grab()
                now = self._clock()
                if self.config.record_path is not None and recorder is None:
                    recorder = RoundRecorder(self.config.record_path, frame)
                allowed = gate.observe(frame)
                ready = RoundGate.player_ready(frame) if allowed else False
                candidate = False
                clicked = False
                if gate.finished:
                    LOG.info("本局結束或畫面無法確認，已停止；不會點擊下一步")
                    self.stop_reason = "round_finished"
                    if recorder:
                        recorder.add(frame, now-started, hud=False, ready=False,
                                     candidate=False, clicked=False,
                                     detector_score=detector.last_score)
                    break
                if not allowed or not ready:
                    if recorder:
                        recorder.add(frame, now-started, hud=allowed, ready=ready,
                                     candidate=False, clicked=False,
                                     detector_score=detector.last_score)
                    self._sleep(0.02)
                    continue
                candidate = detector.observe(frame, now)
                if candidate:
                    self.candidate_count += 1
                    if not self.config.observe_only:
                        fresh = capture.grab()
                        if not gate.observe(fresh):
                            self.stop_reason = "round_finished"
                            if recorder:
                                recorder.add(fresh, self._clock()-started, hud=False,
                                             ready=False, candidate=False, clicked=False,
                                             detector_score=detector.last_score)
                            break
                        if RoundGate.player_ready(fresh) and self.tap_jump(fresh):
                            self.tap_count += 1
                            clicked = True
                self.last_detector_score = detector.last_score
                if recorder:
                    recorder.add(frame, now-started, hud=allowed, ready=ready,
                                 candidate=candidate, clicked=clicked,
                                 detector_score=detector.last_score,
                                 input_elapsed=(self.last_tap_at-started)
                                 if clicked and self.last_tap_at is not None else None)
                self._sleep(0.012)
        except Exception as error:
            self.last_error = error
            self.stop_reason = "error"
            LOG.exception("自動跳繩已停止")
        finally:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
            if recorder:
                try:
                    recorder.close(stop_reason=self.stop_reason,
                                   tap_count=self.tap_count,
                                   candidate_count=self.candidate_count,
                                   error=str(self.last_error) if self.last_error else None)
                except Exception as error:
                    LOG.exception("無法完成錄影紀錄")
                    if self.last_error is None:
                        self.last_error = error
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
        print("按 F9 或 Ctrl+C 停止。")
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
