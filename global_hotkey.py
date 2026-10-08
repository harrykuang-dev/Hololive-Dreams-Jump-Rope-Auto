"""Windows global hotkey listener; never calls Tk or waits for its event loop."""
import ctypes
from ctypes import wintypes
import threading
from app_settings import parse_stop_hotkey

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


def windows_hotkey(value):
    mods, key = parse_stop_hotkey(value)
    return sum({0x11:2, 0x12:1, 0x10:4}[m] for m in mods), key


class GlobalHotkey:
    def __init__(self, callback, report):
        self.callback, self.report = callback, report
        self._lock = threading.Lock()
        self._desired = ('F8', True, 0)
        self._stop = threading.Event()
        self.thread = None
        self.thread_id = None
        self.registration_id = None

    def start(self):
        self.thread = threading.Thread(target=self._listen, name='start-hotkey', daemon=True)
        self.thread.start()

    def configure(self, value=None, enabled=None):
        with self._lock:
            old, active, version = self._desired
            desired = (old if value is None else value, active if enabled is None else enabled)
            if desired != (old, active):
                self._desired = (*desired, version+1)

    def close(self):
        self._stop.set()

    def _listen(self):
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        register = user.RegisterHotKey
        register.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        register.restype = wintypes.BOOL
        unregister = user.UnregisterHotKey
        unregister.argtypes = (wintypes.HWND, ctypes.c_int)
        unregister.restype = wintypes.BOOL
        peek = user.PeekMessageW
        peek.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
        peek.restype = wintypes.BOOL
        get_state = user.GetAsyncKeyState
        get_state.argtypes = (ctypes.c_int,)
        get_state.restype = ctypes.c_short
        kernel.GetCurrentThreadId.restype = wintypes.DWORD
        self.thread_id = kernel.GetCurrentThreadId()
        msg = wintypes.MSG()
        peek(ctypes.byref(msg), None, 0, 0, 0)  # Create this thread's queue.
        version, registered, identity = -1, False, 0
        blocked = False
        try:
            while not self._stop.is_set():
                with self._lock:
                    value, enabled, revision = self._desired
                if revision != version:
                    if registered:
                        unregister(None, identity)
                    registered = False
                    self.registration_id = None
                    version = revision
                    identity = identity % 0xBFFE + 1
                    modifiers, key = windows_hotkey(value)
                    blocked = bool(get_state(key) & 0x8000)
                    if enabled:
                        registered = bool(register(None, identity, modifiers | MOD_NOREPEAT, key))
                        self.registration_id = identity if registered else None
                        self.report(value, registered, 0 if registered else ctypes.get_last_error())
                if blocked and not get_state(key) & 0x8000:
                    blocked = False
                while peek(ctypes.byref(msg), None, 0, 0, 1):
                    if (registered and enabled and not blocked and msg.message == WM_HOTKEY
                            and msg.wParam == identity
                            and msg.lParam & 0xFFFF == modifiers
                            and (msg.lParam >> 16) & 0xFFFF == key):
                        # Snapshot current permission too: capture may have
                        # disabled the listener since this loop began.
                        with self._lock:
                            allowed = self._desired == (value, True, version)
                        if allowed:
                            self.callback()
                self._stop.wait(.01)
        except Exception as exc:
            self.report(value, False, str(exc))
        finally:
            if registered:
                unregister(None, identity)
            self.registration_id = None
