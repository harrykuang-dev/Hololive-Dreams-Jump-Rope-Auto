"""Mocked GDI contracts; these tests never capture or interact with the desktop."""
import ctypes
from types import SimpleNamespace
import numpy as np
import pytest
import vision
from jump_rope_bot import BotConfig


@pytest.fixture
def desktop(monkeypatch):
    state = SimpleNamespace(foreground=123, iconic=False, rect=(100, 100, 200, 180),
                            above=0, overlay=(120, 110, 160, 150), cloaked=0)
    monkeypatch.setattr(vision.win32gui, 'IsWindow', lambda _: True)
    monkeypatch.setattr(vision.win32gui, 'IsIconic', lambda h: state.iconic if h == 123 else False)
    monkeypatch.setattr(vision.win32gui, 'GetForegroundWindow', lambda: state.foreground)
    monkeypatch.setattr(vision.win32api, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(vision.win32gui, 'GetClientRect', lambda _: (0, 0, 100, 80))
    monkeypatch.setattr(vision.win32gui, 'ClientToScreen', lambda *args: state.rect[:2])
    monkeypatch.setattr(vision.win32gui, 'GetWindow', lambda h, _: state.above if h == 123 else 0)
    monkeypatch.setattr(vision.win32gui, 'IsWindowVisible', lambda _: True)
    monkeypatch.setattr(vision.win32gui, 'GetWindowRect', lambda _: state.overlay)
    def cloak(hwnd, attr, result, size):
        result._obj.value = state.cloaked
        return 0
    user = SimpleNamespace(GetSystemMetrics=lambda n: {0: 1920, 1: 1080, 76: 0, 77: 0, 78: 1920, 79: 1080}[n],
                           SetThreadDpiAwarenessContext=lambda _: None)
    monkeypatch.setattr(vision, 'ctypes', SimpleNamespace(windll=SimpleNamespace(
        user32=user, dwmapi=SimpleNamespace(DwmGetWindowAttribute=cloak)),
        c_void_p=ctypes.c_void_p, c_int=ctypes.c_int, byref=ctypes.byref, sizeof=ctypes.sizeof))
    return state


def test_visible_client_uses_physical_client_origin(desktop):
    assert vision.ScreenCapture(123)._visible_client() == (100, 100, 100, 80)


@pytest.mark.parametrize('change', ['focus', 'minimized', 'offscreen', 'overlay'])
def test_fast_capture_rejects_unsafe_client(desktop, change):
    if change == 'focus': desktop.foreground = 456
    if change == 'minimized': desktop.iconic = True
    if change == 'offscreen': desktop.rect = (-10, 0, 90, 80)
    if change == 'overlay': desktop.above = 456
    with pytest.raises(RuntimeError):
        vision.ScreenCapture(123)._visible_client()


def test_hidden_virtual_desktop_window_is_not_a_visible_overlay(desktop):
    desktop.above, desktop.cloaked = 456, 1
    assert vision.ScreenCapture(123)._visible_client() == (100, 100, 100, 80)


@pytest.mark.parametrize('title', ['ChatGPT is using your computer. Esc to cancel',
                                 'Codex Computer Use Cursor Overlay'])
def test_launch_indicator_is_transient_error_not_capture_permission(desktop, monkeypatch, title):
    desktop.above = 456
    monkeypatch.setattr(vision.win32gui, 'GetWindowText', lambda _: title)
    with pytest.raises(vision.TemporaryCaptureOverlayError):
        vision.ScreenCapture(123)._visible_client()


def test_buffers_reused_frames_owned_resize_and_close_release(desktop, monkeypatch):
    counts = {'allocate': 0, 'delete': 0, 'release': 0, 'blit': 0}
    state = {'rect': (10, 20, 4, 2)}
    class DC:
        def CreateCompatibleDC(self): return DC()
        def SelectObject(self, bitmap): return 'old'
        def DeleteDC(self): pass
        def BitBlt(self, origin, size, source, pos, flags):
            counts['blit'] += 1
            assert origin == (0, 0) and pos == (10, 20)
    class Bitmap:
        def CreateCompatibleBitmap(self, source, w, h):
            counts['allocate'] += 1
            self.size = (h, w, 4)
        def GetBitmapBits(self, copy): return np.full(self.size, counts['blit'], np.uint8).tobytes()
        def GetHandle(self): return 42
    monkeypatch.setattr(vision.win32gui, 'GetDC', lambda _: 99)
    monkeypatch.setattr(vision.win32gui, 'ReleaseDC', lambda *a: counts.__setitem__('release', counts['release']+1))
    monkeypatch.setattr(vision.win32gui, 'DeleteObject', lambda *a: counts.__setitem__('delete', counts['delete']+1))
    monkeypatch.setattr(vision.win32ui, 'CreateDCFromHandle', lambda _: DC())
    monkeypatch.setattr(vision.win32ui, 'CreateBitmap', Bitmap)
    capture = vision.ScreenCapture(123)
    monkeypatch.setattr(capture, '_visible_client', lambda: state['rect'])
    first = capture.grab()
    second = capture.grab()
    assert counts['allocate'] == 1 and first.shape == (2, 4, 3)
    assert np.all(first == 1) and np.all(second == 2)
    state['rect'] = (10, 20, 6, 4)
    assert capture.grab().shape == (4, 6, 3)
    capture.close()
    capture.close()
    assert counts['allocate'] == counts['delete'] == counts['release'] == 2
    with pytest.raises(RuntimeError, match='closed'):
        capture.grab()


def test_backend_validation():
    for backend in ('screen', 'printwindow', 'dxgi'):
        BotConfig(capture_backend=backend).validate()
    with pytest.raises(ValueError):
        BotConfig(capture_backend='cached').validate()


def fake_dxgi(desktop, frames):
    class Camera:
        width, height = 1920, 1080
        released = 0
        def grab(self, **kwargs):
            assert kwargs == dict(region=(100, 100, 200, 180), copy=True, new_frame_only=True)
            return next(frames)
        def release(self): self.released += 1
    return Camera()


def test_dxgi_waits_for_fresh_frame_and_releases_once(desktop):
    frame = np.ones((80, 100, 3), np.uint8)
    camera = fake_dxgi(desktop, iter([None, frame]))
    calls = []
    capture = vision.DxgiCapture(123, camera_factory=lambda **kwargs: camera,
                                 sleeper=lambda delay: calls.append(delay))
    assert capture.grab() is frame
    assert calls == [.001]
    capture.close(); capture.close()
    assert camera.released == 1
    with pytest.raises(RuntimeError, match='closed'):
        capture.grab()


def test_dxgi_timeout_never_returns_cached_frame(desktop):
    camera = fake_dxgi(desktop, iter([None]*10))
    ticks = iter([0, .25, .50, .50, .50])  # Includes capture-event logging clock reads.
    capture = vision.DxgiCapture(123, camera_factory=lambda **kwargs: camera,
                                 clock=lambda: next(ticks), sleeper=lambda _: None)
    with pytest.raises(RuntimeError, match='舊幀'):
        capture.grab()
    capture.close()
    assert camera.released == 1


def test_dxgi_f9_interrupts_wait_without_returning_a_frame(desktop, monkeypatch):
    camera = fake_dxgi(desktop, iter([None]))
    capture = vision.DxgiCapture(123, camera_factory=lambda **kwargs: camera)
    keys = iter([0, 0x8000])
    monkeypatch.setattr(vision.win32api, 'GetAsyncKeyState', lambda _: next(keys))
    with pytest.raises(RuntimeError, match='F9'):
        capture.grab()
    capture.close()


def test_dxgi_wrong_monitor_dimensions_release_camera(desktop):
    camera = fake_dxgi(desktop, iter([]))
    camera.width = 1280
    with pytest.raises(RuntimeError, match='主螢幕'):
        vision.DxgiCapture(123, camera_factory=lambda **kwargs: camera)
    assert camera.released == 1


@pytest.mark.parametrize('change', ['focus', 'minimized', 'offscreen', 'overlay', 'move'])
def test_dxgi_rechecks_safety_after_capture(desktop, change):
    camera = fake_dxgi(desktop, iter([]))
    capture = vision.DxgiCapture(123, camera_factory=lambda **kwargs: camera)
    def grabbed(**kwargs):
        if change == 'focus': desktop.foreground = 456
        if change == 'minimized': desktop.iconic = True
        if change == 'offscreen': desktop.rect = (-10, 0, 90, 80)
        if change == 'overlay': desktop.above = 456
        if change == 'move': desktop.rect = (110, 100, 210, 180)
        return np.ones((80, 100, 3), np.uint8)
    camera.grab = grabbed
    with pytest.raises(RuntimeError):
        capture.grab()
    capture.close()
