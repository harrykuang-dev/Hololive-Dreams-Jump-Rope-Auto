"""Automatic jump-rope player for the hololive-Dreams Windows game."""

from __future__ import annotations

import argparse
import ctypes
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import win32api
import win32con
import win32gui

from vision import GameCapture, RopeDetector, RopeTimingEstimator

LOG = logging.getLogger("jump-rope-auto")


class GameNotFoundError(RuntimeError):
    """Raised when the game window cannot be found."""


@dataclass(frozen=True)
class BotConfig:
    window_title: str = "hololive-Dreams"
    window_class: str = "UnityWndClass"
    # Only used by the retained rapid diagnostic strategy.
    tap_interval: float = 0.045
    # Keep the key down longer than a 60 Hz frame so Unity cannot miss it.
    key_down_time: float = 0.025
    refocus_interval: float = 1.0
    jump_x_ratio: float = 0.92
    jump_y_ratio: float = 0.91
    acceleration_per_jump: float = 0.0
    minimum_interval: float = 0.02
    startup_delay: float = 0.0
    strategy: str = "vision"

    def validate(self) -> None:
        if not 0.02 <= self.tap_interval <= 2.0:
            raise ValueError("tap_interval must be between 0.02 and 2.0 seconds")
        if not 0.001 <= self.key_down_time < self.tap_interval:
            raise ValueError("key_down_time must be positive and shorter than tap_interval")
        if self.strategy not in {"vision", "rapid"}:
            raise ValueError("strategy must be vision or rapid")
        if self.minimum_interval <= 0 or self.minimum_interval > self.tap_interval:
            raise ValueError("minimum_interval must be positive and no greater than tap_interval")
        if self.acceleration_per_jump < 0 or self.startup_delay < 0:
            raise ValueError("acceleration_per_jump and startup_delay cannot be negative")

    def interval_for_jump(self, jump_number: int) -> float:
        """Return the delay after a sent jump input."""
        if self.strategy in {"rapid", "vision"}:
            return self.tap_interval
        return max(self.minimum_interval, self.tap_interval - jump_number * self.acceleration_per_jump)


class JumpRopeBot:
    """Keeps the player airborne by tapping Space whenever the game can accept it."""

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
        self.last_error: Exception | None = None
        self.last_detector_score = 0.0

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
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception as error:
            raise RuntimeError("無法將遊戲切到前景；請手動點一下遊戲視窗後重試。") from error
        self._hwnd = hwnd
        return hwnd

    def tap_jump(self) -> None:
        """Click the game's own Jump button, which Unity accepts reliably."""
        if not self._hwnd:
            raise GameNotFoundError("遊戲視窗已關閉。")
        left, top, right, bottom = win32gui.GetClientRect(self._hwnd)
        client_x = round((right - left) * self.config.jump_x_ratio)
        client_y = round((bottom - top) * self.config.jump_y_ratio)
        screen_x, screen_y = win32gui.ClientToScreen(self._hwnd, (client_x, client_y))
        win32api.SetCursorPos((screen_x, screen_y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        self._sleep(self.config.key_down_time)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)

    def _loop(self) -> None:
        self._running.set()
        self.tap_count = 0
        self.last_error = None
        next_tap = self._clock() + self.config.startup_delay
        next_focus_check = next_tap
        try:
            self.focus_game()
            detector = RopeDetector()
            timing = RopeTimingEstimator()
            capture = GameCapture(self._hwnd)
            while not self._stop.is_set():
                now = self._clock()
                if now >= next_focus_check:
                    if not self._hwnd or not win32gui.IsWindow(self._hwnd):
                        raise GameNotFoundError("遊戲視窗已關閉。")
                    if win32gui.GetForegroundWindow() != self._hwnd:
                        LOG.warning("遊戲失去焦點，正在重新取得焦點")
                        self.focus_game()
                    next_focus_check = now + self.config.refocus_interval
                if self.config.strategy == "vision":
                    frame = capture.grab()
                    if timing.should_jump(detector.observe(frame, now), now):
                        self.tap_jump()
                        self.tap_count += 1
                    self.last_detector_score = detector.last_score
                    self._sleep(0.012)
                elif now >= next_tap:
                    self.tap_jump()
                    self.tap_count += 1
                    next_tap = max(next_tap + self.config.interval_for_jump(self.tap_count - 1), self._clock())
                else:
                    self._sleep(min(next_tap - now, 0.005))
        except Exception as error:
            self.last_error = error
            LOG.exception("自動跳繩已停止")
        finally:
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
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
    parser.add_argument("--interval", type=float, default=0.045, help="舊版連點間隔（秒）")
    parser.add_argument("--startup-delay", type=float, default=0, help="開始跳躍前的等待秒數")
    parser.add_argument("--rapid", action="store_true", help="使用舊版連點診斷模式；預設為視覺辨識")
    parser.add_argument("--duration", type=float, help="測試秒數；省略則持續執行")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bot = JumpRopeBot(BotConfig(
        tap_interval=args.interval,
        startup_delay=args.startup_delay,
        minimum_interval=0.02,
        strategy="rapid" if args.rapid else "vision",
    ))
    try:
        print("開始自動跳繩；按 Ctrl+C 停止。")
        bot.run(args.duration)
    except KeyboardInterrupt:
        bot.stop()
    except (GameNotFoundError, RuntimeError, ValueError) as error:
        print(f"錯誤：{error}")
        return 1
    finally:
        print(f"已停止，共送出 {bot.tap_count} 次跳躍輸入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
