"""Screen capture and motion-based rope detection for Hololive Dreams."""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np
import win32gui
import win32ui


class GameCapture:
    """Capture a Unity window even when another application covers it."""

    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd

    def grab(self) -> np.ndarray:
        left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
        width, height = right - left, bottom - top
        window_dc = win32gui.GetWindowDC(self.hwnd)
        source = win32ui.CreateDCFromHandle(window_dc)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(source, width, height)
            memory.SelectObject(bitmap)
            # PW_RENDERFULLCONTENT captures Unity correctly on current Windows.
            if not __import__("ctypes").windll.user32.PrintWindow(self.hwnd, memory.GetSafeHdc(), 2):
                raise RuntimeError("無法擷取遊戲畫面")
            pixels = bitmap.GetBitmapBits(True)
            return np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory.DeleteDC()
            source.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, window_dc)


@dataclass(frozen=True)
class RopeDetectorConfig:
    # The character line occupies this region at every supported resolution.
    x_start: float = 0.33
    x_end: float = 0.76
    y_start: float = 0.54
    y_end: float = 0.85
    min_line_fraction: float = 0.18
    min_event_gap: float = 0.45


class RopeDetector:
    """Find the moving rope when it enters the players' foot-level zone.

    Static scenery and large foreground props are rejected by differencing two
    frames. The remaining thin, long moving segment is then found with Hough
    lines. A single event is emitted for each rope pass, never a fixed timer.
    """

    def __init__(self, config: RopeDetectorConfig | None = None) -> None:
        self.config = config or RopeDetectorConfig()
        self._previous: np.ndarray | None = None
        self._last_event = float("-inf")
        self.last_score = 0.0

    def _roi(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        return frame[
            int(height * self.config.y_start):int(height * self.config.y_end),
            int(width * self.config.x_start):int(width * self.config.x_end),
        ]

    def observe(self, frame: np.ndarray, now: float | None = None) -> bool:
        if now is None:
            now = time.perf_counter()
        roi = self._roi(frame)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if self._previous is None or self._previous.shape != gray.shape:
            self._previous = gray
            return False

        difference = cv2.absdiff(gray, self._previous)
        self._previous = gray
        moving = cv2.threshold(difference, 32, 255, cv2.THRESH_BINARY)[1]
        # The physical rope has a muted blue strand.  Unlike the bright white
        # highlights, this color remains present under every lighting effect.
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        rope_blue = cv2.inRange(hsv, (100, 45, 70), (120, 190, 230))
        moving = cv2.bitwise_and(moving, rope_blue)
        moving = cv2.morphologyEx(
            moving, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3))
        )
        edges = cv2.Canny(moving, 40, 120)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=28,
            minLineLength=max(35, int(roi.shape[1] * self.config.min_line_fraction)),
            maxLineGap=24,
        )
        score = 0.0
        if lines is not None:
            for x1, y1, x2, y2 in lines.reshape(-1, 4):
                length = float(np.hypot(x2 - x1, y2 - y1))
                # The rope can be a shallow curve; accept only near-horizontal
                # pieces near the lower half of the player zone.
                if abs(y2 - y1) <= max(16, abs(x2 - x1) * 0.42) and (y1 + y2) / 2 > roi.shape[0] * 0.28:
                    score = max(score, length)
        self.last_score = score
        if score and now - self._last_event >= self.config.min_event_gap:
            self._last_event = now
            return True
        return False


class RopeTimingEstimator:
    """Keep a visual lock on the rope through brief foreground occlusions."""

    def __init__(self, initial_period: float = 1.25) -> None:
        self.period = initial_period
        self._last_rope: float | None = None
        self._next_predicted: float | None = None

    def should_jump(self, rope_seen: bool, now: float) -> bool:
        if rope_seen:
            if self._last_rope is not None:
                measured = now - self._last_rope
                # Ignore duplicate detector edges and unrelated moving props.
                if 0.62 <= measured <= 1.8:
                    self.period = 0.72 * self.period + 0.28 * measured
            self._last_rope = now
            self._next_predicted = now + self.period
            return True
        if self._next_predicted is not None and now >= self._next_predicted:
            # This is only a short occlusion bridge; the next visual event
            # replaces this estimate. Advance from the planned phase to avoid
            # drift caused by polling latency.
            self._next_predicted += self.period
            return True
        return False
