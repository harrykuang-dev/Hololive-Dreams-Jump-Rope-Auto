"""Bounded, session-wide foreground recovery; never clicks the game."""
import ctypes
from ctypes import wintypes
from datetime import datetime
import logging
from pathlib import PureWindowsPath
import time
import win32api
import win32con
import win32gui
import win32process

LOG = logging.getLogger('jump-rope-auto')


def window_snapshot(hwnd):
    result = {'hwnd': int(hwnd or 0)}
    if not hwnd:
        return result
    queries = {'title': win32gui.GetWindowText, 'class': win32gui.GetClassName,
               'visible': win32gui.IsWindowVisible, 'minimized': win32gui.IsIconic,
               'client_rect': win32gui.GetClientRect}
    for key, query in queries.items():
        try:
            result[key] = query(hwnd)
        except Exception as error:
            result[key+'_error'] = str(error)
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        result['pid'] = pid
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                                     wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                length = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(length.value)
                if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                    # Process basename only; do not collect unrelated full paths.
                    result['process'] = PureWindowsPath(buffer.value).name
            finally:
                kernel.CloseHandle(handle)
    except Exception as error:
        result['process_error'] = str(error)
    return result


class FocusRecovery:
    def __init__(self, *, limit=3, diagnostics=False, sink=None,
                 clock=time.perf_counter, sleeper=time.sleep):
        self.limit, self.attempts, self.successes = limit, 0, 0
        self.diagnostics, self.sink = diagnostics, sink
        self.clock, self.sleep = clock, sleeper
        self.events = []
        self.initial_focus_done = False

    def note(self, event, **values):
        if not self.diagnostics:
            return
        entry = dict(event=event, time=datetime.now().astimezone().isoformat(),
                     monotonic_ns=time.perf_counter_ns(), attempts=self.attempts,
                     limit=self.limit, **values)
        self.events.append(entry)
        if self.sink:
            try:
                self.sink(entry)
            except Exception:
                # Keep the in-memory record for the final ZIP. Do not replace
                # the underlying focus/stop reason with an auxiliary log error.
                LOG.exception('無法寫入焦點診斷；記錄保留至結束時打包')

    def ensure(self, hwnd, *, stopped, release=lambda: None):
        foreground = win32gui.GetForegroundWindow()
        if foreground == hwnd and not win32gui.IsIconic(hwnd):
            return not stopped()
        # No pending DOWN or held mouse input survives a recovery attempt.
        release()
        if stopped():
            return False
        if self.diagnostics:
            stolen = window_snapshot(foreground)
            self.note('focus_lost', target=window_snapshot(hwnd), foreground=stolen)
            LOG.info('遊戲失焦；前景視窗：%r；程序：%s；PID：%s',
                     stolen.get('title', ''), stolen.get('process', ''), stolen.get('pid'))
        while self.attempts < self.limit:
            if stopped() or not win32gui.IsWindow(hwnd):
                return False
            self.attempts += 1
            self.note('recovery_attempt', target_hwnd=hwnd)
            LOG.info('正在切回遊戲（%s/%s）', self.attempts, self.limit)
            alt_owned = False
            try:
                if win32gui.IsIconic(hwnd):
                    ctypes.windll.user32.ShowWindowAsync(ctypes.c_void_p(hwnd), win32con.SW_RESTORE)
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
                if stopped():
                    return False
                # An owned, paired Alt pulse permits Windows foreground
                # activation. Never attach input queues or release a held
                # physical Alt key belonging to the operator.
                if not win32api.GetAsyncKeyState(win32con.VK_MENU) & 0x8000:
                    alt_owned = True
                    win32api.keybd_event(win32con.VK_LMENU, 0x38, 0, 0)
                if stopped():
                    return False
                win32gui.SetForegroundWindow(hwnd)
            except Exception as error:
                self.note('activation_error', error=f'{type(error).__name__}: {error}')
            finally:
                if alt_owned:
                    win32api.keybd_event(win32con.VK_LMENU, 0x38, win32con.KEYEVENTF_KEYUP, 0)
            deadline = self.clock()+1.5
            stable_since = None
            while self.clock() < deadline:
                if stopped() or not win32gui.IsWindow(hwnd):
                    return False
                ready = win32gui.GetForegroundWindow() == hwnd and not win32gui.IsIconic(hwnd)
                if ready:
                    rect = win32gui.GetClientRect(hwnd)
                    ready = rect[2] > rect[0] and rect[3] > rect[1]
                if ready:
                    stable_since = self.clock() if stable_since is None else stable_since
                    if self.clock()-stable_since >= .15:
                        self.successes += 1
                        self.note('recovered', target=window_snapshot(hwnd) if self.diagnostics else None)
                        return True
                else:
                    stable_since = None
                self.sleep(.025)
            self.note('recovery_timeout', foreground=window_snapshot(win32gui.GetForegroundWindow())
                      if self.diagnostics else None)
        self.note('recovery_limit_reached')
        LOG.info('切回遊戲次數已達上限，已停止')
        return False
