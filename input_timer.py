"""High-resolution interruptible Windows wait; no busy loop or timer-rate change.

CreateWaitableTimerExW(HIGH_RESOLUTION) wakes the existing single UP owner.
The wake event interrupts a wait for stop/reset; handles close after join.
"""
import ctypes
from ctypes import wintypes
import math
from input_pulse import Pulse as BasePulse, InputRejected


class HighResolutionWaiter:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.CreateWaitableTimerExW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        k.CreateWaitableTimerExW.restype = wintypes.HANDLE
        k.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
        k.CreateEventW.restype = wintypes.HANDLE
        k.SetEvent.argtypes = (wintypes.HANDLE,)
        k.SetEvent.restype = wintypes.BOOL
        k.SetWaitableTimer.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong), wintypes.LONG,
                                      ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL)
        k.SetWaitableTimer.restype = wintypes.BOOL
        k.WaitForMultipleObjects.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD)
        k.WaitForMultipleObjects.restype = wintypes.DWORD
        k.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        k.CloseHandle.restype = wintypes.BOOL
        self.event = k.CreateEventW(None, False, False, None)
        self.timer = k.CreateWaitableTimerExW(None, None, 2, 0x1F0003)
        if not self.event or not self.timer:
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)
        self.handles = (wintypes.HANDLE * 2)(self.event, self.timer)

    def notify(self):
        if self.event and not self.kernel.SetEvent(self.event):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, condition, seconds):
        if seconds is not None:
            due = ctypes.c_longlong(-max(1, math.ceil(seconds * 10_000_000)))
            if not self.kernel.SetWaitableTimer(self.timer, ctypes.byref(due), 0, None, None, False):
                raise ctypes.WinError(ctypes.get_last_error())
        condition.release()
        try:
            result = (self.kernel.WaitForSingleObject(self.event, 0xFFFFFFFF) if seconds is None
                      else self.kernel.WaitForMultipleObjects(2, self.handles, False, 0xFFFFFFFF))
            if result not in (0, 1):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            condition.acquire()

    def close(self):
        for name in ('timer', 'event'):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)


class TimedPulse(BasePulse):
    def __init__(self, down, up):
        super().__init__(down, up, waiter=HighResolutionWaiter())
