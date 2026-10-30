"""One bounded JSON and one issue attachment per developer-mode execution.

Frames are written by the existing diagnostic worker, never the input callback.
Each flushed append leaves a complete JSON document. No system query runs in
the capture loop. Retention limits are explicit in the final record.
"""
from collections import Counter
from datetime import datetime
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import threading
import time
import zipfile
import zlib

ISSUE_LIMIT = 20 * 1024**2


def safe_value(value):
    if isinstance(value, dict):
        return {str(k): safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, Path)):
        text = str(value)
        profile = os.environ.get('USERPROFILE')
        if profile:
            text = text.replace(profile, '%USERPROFILE%').replace(profile.replace('\\', '/'), '%USERPROFILE%')
        return text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, 'item'):
        return safe_value(value.item())
    return str(value)


class DiagnosticLogHandler(logging.Handler):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.setFormatter(logging.Formatter())

    def emit(self, record):
        try:
            self.session.event('log', level=record.levelname, message=record.getMessage(),
                               exception=self.formatter.formatException(record.exc_info)
                               if record.exc_info else None)
        except Exception as error:
            # Logging must not interfere with releasing a held input.
            self.session.error = self.session.error or error


class SessionDiagnostics:
    def __init__(self, directory, metadata=None, *, system=None,
                 trace_limit=8*1024**2, raw_trace_limit=128*1024**2,
                 critical_limit=2*1024**2, image_limit=8*1024**2):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory/'diagnostics.json'
        self.archive = self.directory/'diagnostics.zip'
        self.trace_limit, self.raw_trace_limit = trace_limit, raw_trace_limit
        self.critical_limit, self.image_limit = critical_limit, image_limit
        self.error = None
        self._lock = threading.RLock()
        self._compressed = zlib.compressobj(6, zlib.DEFLATED, -15)
        self._compressed_bytes = self._trace_bytes = self._critical_bytes = 0
        self._events = 0
        self.omitted = Counter()
        self.images = {}
        self._image_bytes = 0
        self.closed = False
        self._last_flush = 0.
        header = dict(schema_version=3, app_version=(metadata or {}).get('app_version'),
                      created_at=datetime.now().astimezone().isoformat(),
                      session=metadata or {}, system=system or {},
                      timestamp_semantics={'monotonic_ns': 'perf_counter_ns; same process clock',
                          'capture_ns': 'capture returned; presentation time is unknown',
                          'native_return_ns': 'native input call returned; game delivery time is unknown',
                          't': 'seconds relative to the individual round'},
                      privacy={'automatic_upload': False, 'full_process_list': False,
                               'foreground_window_titles': True},
                      retention={'trace_compressed_budget': trace_limit,
                          'trace_raw_budget': raw_trace_limit, 'critical_raw_budget': critical_limit,
                          'image_budget': image_limit, 'archive_limit_bytes': ISSUE_LIMIT,
                          'policy': 'Full observations until the trace budget; summaries continue. '
                                    'Images retain recent failure evidence before routine screenshots. '
                                    'Final attachments list is authoritative for retained images.'})
        # Text mode seek cookies are used rather than byte offsets, including
        # for non-ASCII window titles and messages.
        self._stream = self.path.open('x+', encoding='utf-8', newline='\n')
        initial = json.dumps(safe_value(header), ensure_ascii=False, allow_nan=False)[:-1]+',"events":[\n'
        self._stream.write(initial)
        self._end = self._stream.tell()
        self._stream.write(']}\n')
        self._stream.flush()
        self._compressed_bytes += len(self._compressed.compress(initial.encode('utf-8')))

    def check_health(self):
        if self.error:
            raise RuntimeError('Session diagnostics could not be saved') from self.error

    def event(self, kind, *, trace=False, **values):
        with self._lock:
            self.check_health()
            if self.closed:
                raise RuntimeError('Session diagnostics already closed')
            entry = {'type':kind, 'monotonic_ns':time.perf_counter_ns(), **values}
            text = json.dumps(safe_value(entry), ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            size = len(text.encode('utf-8'))
            if trace and (self._compressed_bytes >= self.trace_limit or self._trace_bytes+size > self.raw_trace_limit):
                self.omitted[kind] += 1
                return False
            if not trace and self._critical_bytes+size > self.critical_limit:
                self.omitted[kind] += 1
                return False
            try:
                self._append(text)
                if trace:
                    self._trace_bytes += size
                else:
                    self._critical_bytes += size
                return True
            except Exception as error:
                self.error = error
                raise

    def _append(self, text):
        piece = (',\n' if self._events else '')+text
        previous = self._end
        try:
            self._stream.seek(previous)
            self._stream.write(piece)
            end = self._stream.tell()
            self._stream.write('\n]}\n')
            self._stream.truncate()
        except Exception:
            # Repair the old delimiter within already allocated disk space.
            try:
                self._stream.seek(previous)
                self._stream.write('\n]}\n')
                self._stream.truncate()
                self._stream.flush()
            except Exception:
                pass
            raise
        self._end = end
        self._events += 1
        self._compressed_bytes += len(self._compressed.compress(piece.encode('utf-8')))
        if time.monotonic()-self._last_flush >= .25:
            self._stream.flush()
            self._last_flush = time.monotonic()

    def image(self, path, data, *, priority=1):
        path = Path(path).resolve()
        base = self.directory.resolve()
        if not path.is_relative_to(base):
            raise ValueError('Diagnostic image is outside the session directory')
        relative = path.relative_to(base).as_posix()
        with self._lock:
            if len(data) > self.image_limit:
                self.omitted['image'] += 1
                return False
            while self._image_bytes+len(data) > self.image_limit:
                key = min(self.images, key=lambda key: self.images[key]['priority'])
                old = self.images[key]
                if old['priority'] > priority:
                    self.omitted['image'] += 1
                    return False
                (base/key).unlink(missing_ok=True)
                self._image_bytes -= old['bytes']
                del self.images[key]
                self.omitted['image_evicted'] += 1
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.images[relative] = dict(bytes=len(data), priority=priority,
                                        sha256=hashlib.sha256(data).hexdigest())
            self._image_bytes += len(data)
        return True

    def close(self, **summary):
        with self._lock:
            if self.closed:
                return
            # Reserve the final summary independently of optional trace/log
            # budgets so omissions and the actual stop reason always survive.
            summary.update(omitted_records=dict(self.omitted), attachments=self.images,
                           retained_events=self._events, diagnostic_error=str(self.error) if self.error else None)
            try:
                self._append(json.dumps(safe_value(dict(type='session_finished',
                    monotonic_ns=time.perf_counter_ns(), **summary)), ensure_ascii=False, allow_nan=False))
                self._stream.flush()
                os.fsync(self._stream.fileno())
            finally:
                self._stream.close()
                self.closed = True

    def package(self, *, limit=ISSUE_LIMIT):
        if not self.closed:
            raise RuntimeError('Close diagnostics before packaging')
        temporary = self.archive.with_suffix('.zip.tmp')
        files = [self.path]+[self.directory/name for name in self.images]
        self._zip(temporary, files)
        if temporary.stat().st_size > limit:
            temporary.unlink(missing_ok=True)
            raise RuntimeError('Diagnostic ZIP exceeds the attachment budget; diagnostics.json is preserved')
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Diagnostic ZIP verification failed')
        temporary.replace(self.archive)
        return self.archive

    def _zip(self, path, files):
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in sorted(files):
                archive.write(file, file.relative_to(self.directory).as_posix(),
                              compress_type=zipfile.ZIP_STORED if file.suffix == '.jpg' else zipfile.ZIP_DEFLATED)
