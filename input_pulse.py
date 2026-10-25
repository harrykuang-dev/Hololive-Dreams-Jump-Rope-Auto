"""One input owner; context and the 25 ms deadline belong to the held pulse."""
import threading
import time


class InputRejected(Exception):
    """Policy cancellation guaranteed to occur BEFORE any native DOWN."""


class Pulse:
    def __init__(self, down, up, *, clock=time.perf_counter_ns, waiter=None):
        self._down, self._up, self._clock = down, up, clock
        self._condition = threading.Condition()
        self._waiter = waiter
        self._context = None
        self._deadline = None
        self._closed = False
        self.error = None
        self.last_rejection = None
        self._thread = threading.Thread(target=self._loop, name='jump-input-release', daemon=True)
        self._thread.start()

    def press(self, context, *, valid_until_ns):
        with self._condition:
            self.last_rejection = ('closed' if self._closed else 'input_error' if self.error else
                                   'held' if self._context is not None else
                                   'expired' if valid_until_ns is not None and self._clock() > valid_until_ns else None)
            if self.last_rejection:
                return False
            self._context = context
            try:
                # Use native DOWN return time, before metadata bookkeeping.
                down_ns = self._down(context)
                self._deadline = down_ns + 25_000_000
            except InputRejected as rejection:
                # No input has been delivered. Do not emit a phantom UP or
                # poison the owner after an ordinary freshness cancellation.
                self._context = self._deadline = None
                self.last_rejection = str(rejection)
                self._notify()
                return False
            except BaseException as error:
                self.error = error
                try:
                    self._release('down_error')
                finally:
                    self._notify()
                raise
            self._notify()
            return True

    def _notify(self):
        self._condition.notify_all()
        if self._waiter is not None:
            self._waiter.notify()

    def _wait(self, seconds=None):
        if self._waiter is None:
            self._condition.wait(seconds)
        else:
            self._waiter.wait(self._condition, seconds)

    def _release(self, reason):
        if self._context is None:
            return
        try:
            self._up(self._context, reason)
        except BaseException as error:
            self.error = self.error or error
            raise
        self._context = self._deadline = None

    def reset(self, reason='reset'):
        with self._condition:
            try:
                self._release(reason)
            finally:
                self._notify()

    def _loop(self):
        with self._condition:
            while not self._closed:
                if self._deadline is None:
                    try:
                        self._wait()
                    except BaseException as error:
                        self.error = self.error or error
                        self._closed = True
                    continue
                remaining = (self._deadline-self._clock())/1e9
                if remaining > 0:
                    try:
                        self._wait(remaining)
                    except BaseException as error:
                        self.error = self.error or error
                        try:
                            self._release('wait_error')
                        finally:
                            self._closed = True
                    continue
                try:
                    self._release('deadline')
                except BaseException:
                    self._closed = True

    def close(self):
        try:
            with self._condition:
                try:
                    # One cleanup attempt if the timer's native UP failed.
                    self._release('close')
                finally:
                    self._closed = True
                    self._notify()
        finally:
            self._thread.join(timeout=1)
        if self._thread.is_alive():
            raise RuntimeError('Input release thread did not exit')
        if self._waiter is not None:
            self._waiter.close()
        if self.error:
            raise RuntimeError('Input callback failed') from self.error
