"""Screen capture and motion-based rope detection for Hololive Dreams."""

from __future__ import annotations

import time
import ctypes
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
        # Window rectangles and PrintWindow must use the same physical pixels.
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
        width, height = right - left, bottom - top
        window_dc = win32gui.GetWindowDC(self.hwnd)
        source = win32ui.CreateDCFromHandle(window_dc)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(source, width, height)
            previous_bitmap = memory.SelectObject(bitmap)
            # PW_RENDERFULLCONTENT captures Unity correctly on current Windows.
            if not __import__("ctypes").windll.user32.PrintWindow(self.hwnd, memory.GetSafeHdc(), 2):
                raise RuntimeError("無法擷取遊戲畫面")
            pixels = bitmap.GetBitmapBits(True)
            frame = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
            cx, cy = win32gui.ClientToScreen(self.hwnd, (0, 0))
            _, _, cw, ch = win32gui.GetClientRect(self.hwnd)
            return frame[cy-top:cy-top+ch, cx-left:cx-left+cw]
        finally:
            if 'previous_bitmap' in locals():
                memory.SelectObject(previous_bitmap)
            win32gui.DeleteObject(bitmap.GetHandle())
            memory.DeleteDC()
            # The source wraps a borrowed window DC: ReleaseDC, not DeleteDC.
            # PyCDC exposes no Detach method.
            win32gui.ReleaseDC(self.hwnd, window_dc)


@dataclass(frozen=True)
class RopeDetectorConfig:
    # The character line occupies this region at every supported resolution.
    x_start: float = 0.42
    x_end: float = 0.75
    y_start: float = 0.50
    y_end: float = 0.82
    min_line_fraction: float = 0.18
    trigger_line_length: float = 140.0
    clear_line_length: float = 65.0
    min_event_gap: float = 0.62


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
        self._armed = True
        self.last_score = 0.0
        self._target_x: float | None = None

    def _roi(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        if self._target_x is None:
            x_start, x_end = self.config.x_start, self.config.x_end
        else:
            x_start = max(0.05, self._target_x - 0.14)
            x_end = min(0.95, self._target_x + 0.14)
        return frame[
            int(height * self.config.y_start):int(height * self.config.y_end),
            int(width * x_start):int(width * x_end),
        ]

    def update_target_marker(self, frame: np.ndarray) -> bool:
        """Track the yellow arrow above the player controlled by this client."""
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (18, 110, 170), (42, 255, 255))
        # The Jump button is also yellow, so only search the character field.
        mask[int(height * 0.66):, :] = 0
        mask[:, :int(width * 0.18)] = 0
        mask[:, int(width * 0.88):] = 0
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if 40 <= area <= 2500 and h >= 8 and w >= 8:
                candidates.append((area, x + w / 2))
        if not candidates:
            return False
        _, center_x = max(candidates)
        normalized = center_x / width
        changed = self._target_x is None or abs(normalized - self._target_x) > 0.03
        self._target_x = normalized
        if changed:
            self._previous = None
        return changed

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
        # Legacy heuristic, retained only for offline comparisons. This color
        # is not reliable under every lighting effect; never use as a timer.
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
        if score <= self.config.clear_line_length:
            self._armed = True
        if (
            self._armed
            and score >= self.config.trigger_line_length
            and now - self._last_event >= self.config.min_event_gap
        ):
            self._last_event = now
            self._armed = False
            return True
        return False


class RoundGate:
    """Require the live HUD on every frame; latch off after a round ends.

    Conservative pixel checks are evaluated in normalized client coordinates.
    Unknown frames never authorize input. This gate is intentionally independent
    of the rope detector so moving menu artwork cannot authorize a click.
    """

    def __init__(self) -> None:
        self.active = False
        self.finished = False
        self._confirmations = 0

    @staticmethod
    def jump_position(frame: np.ndarray):
        """Locate the yellow arrow inside the observed Jump button region."""
        if frame.size == 0:
            return None
        hsv = cv2.cvtColor(cv2.resize(frame, (960, 540)), cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv[375:490, 750:895], (20, 100, 180), (42, 255, 255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(contour) < 150:
            return None
        m = cv2.moments(contour)
        if not m['m00']:
            return None
        return ((750+m['m10']/m['m00'])/960, (375+m['m01']/m['m00'])/540)

    @staticmethod
    def player_ready(frame: np.ndarray) -> bool:
        """Check the central player's marker, independent of costume."""
        if frame.size == 0:
            return False
        hsv = cv2.cvtColor(cv2.resize(frame, (960, 540)), cv2.COLOR_BGR2HSV)
        region = cv2.inRange(hsv[95:250, 500:600], (18, 110, 170), (42, 255, 255))
        contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            x, y, width, height = cv2.boundingRect(contour)
            if 22 <= area <= 110 and 6 <= width <= 22 and 5 <= height <= 17:
                center_x = (500 + x + width/2) / 960
                center_y = (95 + y + height/2) / 540
                if .53 <= center_x <= .60 and .20 <= center_y <= .45:
                    return True
        return False

    @staticmethod
    def gameplay_visible(frame: np.ndarray) -> bool:
        if frame.size == 0:
            return False
        normalized = cv2.resize(frame, (960, 540))
        hsv = cv2.cvtColor(normalized, cv2.COLOR_BGR2HSV)
        hearts = cv2.inRange(hsv[190:235, 55:155], (35, 100, 130), (85, 255, 255))
        jump = cv2.inRange(hsv[375:490, 750:895], (20, 100, 180), (42, 255, 255))
        score = cv2.inRange(hsv[45:125, 35:155], (0, 0, 210), (180, 65, 255))
        return (np.count_nonzero(hearts) >= 70
                and np.count_nonzero(jump) >= 250
                and np.count_nonzero(score) >= 100)

    def observe(self, frame: np.ndarray) -> bool:
        if self.finished:
            return False
        visible = self.gameplay_visible(frame)
        if not visible:
            self._confirmations = 0
            if self.active:
                self.finished = True
            return False
        self._confirmations += 1
        if self._confirmations >= 3:
            self.active = True
        return self.active
