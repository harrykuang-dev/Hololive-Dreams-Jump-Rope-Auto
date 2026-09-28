"""Screen capture and motion-based rope detection for Hololive Dreams."""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys

import cv2
import numpy as np
import win32gui
import win32ui
import win32con


class PrintWindowCapture:
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


class ScreenCapture:
    """Copy the visible client from the desktop, with reusable GDI resources.

    Unlike PrintWindow this does not ask Unity to render synchronously.
    Foreground, on-screen and unobscured client checks are mandatory. Never
    fall back through an occlusion: another application's pixels are unsafe.
    """
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.size = None
        self.window_dc = self.source = self.memory = self.bitmap = None
        self.previous_bitmap = None
        self.closed = False

    def _visible_client(self):
        if (not win32gui.IsWindow(self.hwnd) or win32gui.IsIconic(self.hwnd)
                or win32gui.GetForegroundWindow() != self.hwnd):
            raise RuntimeError('高速擷取需要遊戲在前景且未最小化；已停止')
        _, _, width, height = win32gui.GetClientRect(self.hwnd)
        x, y = win32gui.ClientToScreen(self.hwnd, (0, 0))
        user = ctypes.windll.user32
        vx, vy = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
        vw, vh = user.GetSystemMetrics(78), user.GetSystemMetrics(79)
        if width <= 0 or height <= 0 or x < vx or y < vy or x+width > vx+vw or y+height > vy+vh:
            raise RuntimeError('遊戲客戶區不完整位於螢幕內；已停止')
        # Walk only the windows above the target in Z order, not all processes.
        above = win32gui.GetWindow(self.hwnd, win32con.GW_HWNDPREV)
        seen = set()
        while above:
            if above in seen:
                raise RuntimeError('視窗順序改變，無法確認無遮擋；已停止')
            seen.add(above)
            if win32gui.IsWindowVisible(above) and not win32gui.IsIconic(above):
                cloaked = ctypes.c_int()
                status = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    ctypes.c_void_p(above), 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                if status != 0 or not cloaked.value:
                    left, top, right, bottom = win32gui.GetWindowRect(above)
                    if max(left, x) < min(right, x+width) and max(top, y) < min(bottom, y+height):
                        raise RuntimeError('其他視窗覆蓋遊戲；高速擷取安全停止')
            above = win32gui.GetWindow(above, win32con.GW_HWNDPREV)
        return x, y, width, height

    def _release_buffers(self):
        try:
            if self.memory is not None and self.previous_bitmap is not None:
                self.memory.SelectObject(self.previous_bitmap)
            if self.bitmap is not None:
                win32gui.DeleteObject(self.bitmap.GetHandle())
            if self.memory is not None:
                self.memory.DeleteDC()
        finally:
            if self.window_dc is not None:
                win32gui.ReleaseDC(0, self.window_dc)
            self.window_dc = self.source = self.memory = self.bitmap = None
            self.previous_bitmap = None
            self.size = None

    def grab(self):
        if self.closed:
            raise RuntimeError('Capture is closed')
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        rect = self._visible_client()
        x, y, width, height = rect
        if self.size != (width, height):
            self._release_buffers()
            try:
                self.window_dc = win32gui.GetDC(0)
                self.source = win32ui.CreateDCFromHandle(self.window_dc)
                self.memory = self.source.CreateCompatibleDC()
                self.bitmap = win32ui.CreateBitmap()
                self.bitmap.CreateCompatibleBitmap(self.source, width, height)
                self.previous_bitmap = self.memory.SelectObject(self.bitmap)
                self.size = width, height
            except Exception:
                self._release_buffers()
                raise
        self.memory.BitBlt((0, 0), (width, height), self.source, (x, y),
                           win32con.SRCCOPY | 0x40000000)  # CAPTUREBLT is absent in some pywin32 builds.
        pixels = self.bitmap.GetBitmapBits(True)
        frame = np.frombuffer(pixels, np.uint8).reshape(height, width, 4)[:, :, :3].copy()
        # A focus/move/overlay race invalidates the frame, including the fresh
        # pre-input capture. Never return a cached or partially shifted frame.
        if self._visible_client() != rect:
            raise RuntimeError('擷取期間視窗位置或尺寸改變；已停止')
        return frame

    def close(self):
        if not self.closed:
            self._release_buffers()
            self.closed = True


class GameCapture:
    def __init__(self, hwnd, backend='screen'):
        if backend not in ('screen', 'printwindow'):
            raise ValueError('Unknown capture backend')
        self.backend = backend
        self.impl = ScreenCapture(hwnd) if backend == 'screen' else PrintWindowCapture(hwnd)

    def grab(self):
        return self.impl.grab()

    def close(self):
        getattr(self.impl, 'close', lambda: None)()


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
        roi = cv2.resize(frame, (960, 540))[375:490, 750:895]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (20, 100, 180), (42, 255, 255))
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
        roi = cv2.resize(frame, (960, 540))[95:250, 500:600]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        region = cv2.inRange(hsv, (18, 110, 170), (42, 255, 255))
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
        hearts = cv2.inRange(cv2.cvtColor(normalized[190:235, 55:155], cv2.COLOR_BGR2HSV), (35, 100, 130), (85, 255, 255))
        jump = cv2.inRange(cv2.cvtColor(normalized[375:490, 750:895], cv2.COLOR_BGR2HSV), (20, 100, 180), (42, 255, 255))
        score = cv2.inRange(cv2.cvtColor(normalized[45:125, 35:155], cv2.COLOR_BGR2HSV), (0, 0, 210), (180, 65, 255))
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


class StartupScreen:
    """Recognize only the known pre-round button/page combinations."""

    BUTTONS = {
        "next": (.842, .909),
        "ok": (.842, .909),
        "event_next": (.842, .909),
        "play": (.866, .909),
    }

    def __init__(self) -> None:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        self.templates = {}
        for name in ("next", "ok", "play"):
            path = root / "assets" / "startup" / f"{name}.png"
            template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if template is None or template.shape != (40, 135):
                raise RuntimeError(f"啟動畫面辨識樣板缺失：{path}")
            ink = template[:, :85]
            # Unity enlarges the hovered button. Match both resting and
            # hover sizes; the page-context check remains mandatory.
            self.templates[name] = [cv2.resize(
                ink, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
                for scale in (.80, .85, .90, 1.0, 1.05)]

    @staticmethod
    def _count(hsv: np.ndarray, roi, lower, upper) -> int:
        x0, y0, x1, y1 = roi
        return int(np.count_nonzero(cv2.inRange(hsv[y0:y1, x0:x1], lower, upper)))

    def identify(self, frame: np.ndarray) -> str | None:
        if frame.size == 0 or RoundGate.gameplay_visible(frame):
            return None
        hsv = cv2.cvtColor(cv2.resize(frame, (960, 540)), cv2.COLOR_BGR2HSV)
        ink = cv2.inRange(hsv[455:525, 745:915], (0, 0, 185), (179, 85, 255))
        scores = {}
        for name, variants in self.templates.items():
            scores[name] = max(float(cv2.matchTemplate(
                ink, variant, cv2.TM_CCOEFF_NORMED).max()) for variant in variants)
        name = max(scores, key=scores.get)
        if scores[name] < .68 or scores[name] - max(
                value for key, value in scores.items() if key != name) < .20:
            return None
        if name == "next":
            old_result = self._count(hsv, (570, 145, 765, 185),
                                     (155, 50, 100), (179, 255, 255)) > 2000
            event_result = (
                self._count(hsv, (490, 150, 900, 410),
                            (0, 0, 170), (179, 65, 255)) > 80000
                and self._count(hsv, (0, 0, 500, 120),
                                (85, 60, 100), (115, 255, 255)) > 30000
            )
            if old_result:
                return "next"
            if event_result:
                return "event_next"
            return None
        elif name == "ok":
            context = self._count(hsv, (490, 150, 900, 410),
                                  (0, 0, 170), (179, 65, 255)) > 60000
        else:
            context = self._count(hsv, (20, 20, 280, 150),
                                  (15, 90, 120), (45, 255, 255)) > 5000
        return name if context else None


class StartupNavigator:
    """Confirm startup pages and bound missed-click retries before gameplay."""

    ORDER = ("next", "ok", "event_next", "play")
    # The selection page can be visible before Unity accepts its button input.
    # Count actual matching captures, not elapsed time, before the one-shot click.
    CONFIRM_FRAMES = {"next": 5, "ok": 5, "event_next": 8, "play": 8}
    RETRY_FRAMES = 12

    def __init__(self, screen: StartupScreen) -> None:
        self.screen = screen
        self.last_seen = None
        self.confirmations = 0
        self.used: set[str] = set()
        self.retried: set[str] = set()
        self.finished = False

    def observe(self, frame: np.ndarray) -> str | None:
        if self.finished:
            return None
        name = self.screen.identify(frame)
        self.confirmations = self.confirmations + 1 if name and name == self.last_seen else 1
        self.last_seen = name
        if name is None:
            return None
        if self.used and self.ORDER.index(name) < max(self.ORDER.index(n) for n in self.used):
            return None
        if name in self.used:
            # The same pre-round page can ignore an early Unity click. Retry
            # once only when it is still visibly the same page; the controller
            # seals this navigator as soon as gameplay is ever seen.
            if name in self.retried or self.confirmations < self.RETRY_FRAMES:
                return None
        elif self.confirmations < self.CONFIRM_FRAMES[name]:
            return None
        return name

    def mark_clicked(self, name: str) -> None:
        if name in self.used:
            self.retried.add(name)
        self.used.add(name)
        self.last_seen = None
        self.confirmations = 0
        if name == "play":
            self.finished = True

    def seal(self) -> None:
        self.finished = True
