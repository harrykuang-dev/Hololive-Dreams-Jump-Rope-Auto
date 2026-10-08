"""Confirm a stable score page before authorizing another round."""
import time
import win32api
import win32con
import win32gui
from vision import GameCapture, RoundGate, StartupScreen, NoFreshFrameError


def wait_for_result_page(hwnd, *, timeout=15., clock=time.perf_counter,
                         sleeper=time.sleep, capture_factory=GameCapture,
                         screen_factory=StartupScreen, stop_requested=lambda: False):
    capture = capture_factory(hwnd)
    screen = screen_factory()
    deadline = clock()+timeout
    confirmations = 0
    try:
        while clock() < deadline:
            if (stop_requested() or win32gui.GetForegroundWindow() != hwnd
                    or win32api.GetAsyncKeyState(win32con.VK_F9) & 0x8000):
                return False
            try:
                frame = capture.grab()
            except NoFreshFrameError:
                continue
            if not RoundGate.gameplay_visible(frame) and screen.identify(frame) == 'next':
                confirmations += 1
                if confirmations >= 5:
                    return True
            else:
                confirmations = 0
            sleeper(.08)
        return False
    finally:
        getattr(capture, 'close', lambda: None)()
