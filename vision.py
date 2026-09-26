"""Screen capture and motion-based rope detection for Hololive Dreams."""

from __future__ import annotations

import ctypes

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
