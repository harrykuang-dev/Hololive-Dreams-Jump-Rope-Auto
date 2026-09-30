"""Local video and timestamped evidence for one bot-controlled game round."""

from __future__ import annotations

import json
import queue
import shutil
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np


class RoundRecorder:
    def __init__(self, path: Path, first_frame: np.ndarray, fps: float = 60.0,
                 *, queue_size: int = 32, max_width: int = 960,
                 spill_bytes: int = 256 * 1024 * 1024,
                 disk_reserve_bytes: int = 256 * 1024 * 1024) -> None:
        if first_frame.ndim != 3 or first_frame.shape[2] != 3:
            raise ValueError("Recording requires a BGR game frame")
        if (not np.isfinite(fps) or fps <= 0 or queue_size < 1 or max_width < 2
                or spill_bytes < 0 or disk_reserve_bytes < 0):
            raise ValueError('Invalid recording rate, queue size or width')
        self.path = Path(path)
        self.fps = fps
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.shape = first_frame.shape
        height, width = first_frame.shape[:2]
        scale = min(1., max_width/width)
        width, height = round(width*scale), round(height*scale)
        # MP4 encoders generally require even dimensions.
        self.size = (width + width % 2, height + height % 2)
        self.writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"mp4v"),
                                      fps, self.size)
        if not self.writer.isOpened():
            self.writer.release()
            raise RuntimeError(f"無法建立錄影：{self.path}")
        self.frames: list[dict] = []
        self._memory_capacity = queue_size
        self._frame_bytes = self.size[0] * self.size[1] * 3
        self._spill_capacity = spill_bytes // self._frame_bytes
        self._disk_reserve_bytes = disk_reserve_bytes
        self._queue = queue.Queue(maxsize=queue_size + self._spill_capacity)
        # Keep at most queue_size pixel buffers in RAM. Overflow goes to a
        # bounded, lossless local spool, in the SAME FIFO as memory frames.
        # No waits for the encoder, dropped frames, or changed MP4 indices.
        self._buffer_lock = threading.Lock()
        self._memory_pending = self._spill_pending = 0
        self._spool_dir = None
        self.spilled_frames = self.spill_peak = self.memory_peak = 0
        self.spill_write_ms = []
        self._last_disk_check = None
        self._error = None
        self._closed = False
        self.written = 0
        self.queue_peak = 0
        self.encode_ms = []
        self._worker = threading.Thread(target=self._encode, daemon=True,
                                        name='round-video-encoder')
        self._worker.start()

    def _encode(self):
        try:
            while True:
                frame = self._queue.get()
                if frame is None:
                    break
                spill = frame if isinstance(frame, Path) else None
                if spill is not None:
                    frame = np.load(spill, allow_pickle=False)
                else:
                    with self._buffer_lock:
                        self._memory_pending -= 1
                started = time.perf_counter()
                self.writer.write(frame)
                self.encode_ms.append((time.perf_counter()-started)*1000)
                self.written += 1
                if spill is not None:
                    spill.unlink()
                    with self._buffer_lock:
                        self._spill_pending -= 1
        except Exception as error:
            self._error = error
        finally:
            self.writer.release()

    def check_health(self):
        if self._error is not None:
            raise RuntimeError(f'錄影編碼失敗：{self._error}') from self._error
        if self._closed:
            raise RuntimeError('Recording is closed')
        now = time.perf_counter()
        if self._last_disk_check is None or now-self._last_disk_check >= .5:
            if shutil.disk_usage(self.path.parent).free < self._disk_reserve_bytes:
                self._error = OSError('錄影磁碟可用空間不足；安全停止')
                raise RuntimeError(str(self._error)) from self._error
            self._last_disk_check = now
        if self._queue.full():
            raise RuntimeError('錄影佇列及有界磁碟緩衝已滿；安全停止，不丟幀或繼續輸入')

    def add(self, frame: np.ndarray, elapsed: float, *, hud: bool, ready: bool,
            candidate: bool, clicked: bool, detector_score: float,
            input_elapsed: float | None = None,
            telemetry: dict | None = None) -> None:
        self.check_health()
        if frame.shape != self.shape:
            raise RuntimeError("遊戲畫面尺寸在錄影中改變，已停止")
        height, width = frame.shape[:2]
        if width > self.size[0]:
            frame = cv2.resize(frame, self.size)
        elif self.size != (width, height):
            frame = cv2.copyMakeBorder(frame, 0, self.size[1] - height,
                                       0, self.size[0] - width,
                                       cv2.BORDER_CONSTANT, value=(0, 0, 0))
        # Reserve RAM without holding the lock during disk I/O or encoding.
        with self._buffer_lock:
            in_memory = self._memory_pending < self._memory_capacity
            if in_memory:
                self._memory_pending += 1
                self.memory_peak = max(self.memory_peak, self._memory_pending)
            elif self._spill_pending >= self._spill_capacity:
                raise RuntimeError('錄影佇列及有界磁碟緩衝已滿；安全停止')
            else:
                self._spill_pending += 1
                self.spill_peak = max(self.spill_peak, self._spill_pending)
        try:
            if in_memory:
                item = frame.copy()  # Capture may reuse its pixel buffer.
            else:
                started = time.perf_counter()
                if shutil.disk_usage(self.path.parent).free < self._disk_reserve_bytes + self._frame_bytes + 128:
                    raise OSError('錄影磁碟可用空間不足；保留空間並安全停止')
                if self._spool_dir is None:
                    self._spool_dir = Path(tempfile.mkdtemp(prefix=self.path.stem+'-spool-', dir=self.path.parent))
                item = self._spool_dir / f'{len(self.frames):08d}.npy'
                np.save(item, frame, allow_pickle=False)
                self.spill_write_ms.append((time.perf_counter()-started)*1000)
                self.spilled_frames += 1
            self._queue.put_nowait(item)
        except Exception as error:
            with self._buffer_lock:
                if in_memory:
                    self._memory_pending -= 1
                else:
                    self._spill_pending -= 1
            self._error = error
            raise RuntimeError(f'錄影緩衝失敗；安全停止：{error}') from error
        self.queue_peak = max(self.queue_peak, self._queue.qsize())
        entry = {
            "t": round(elapsed, 4), "hud": hud, "ready": ready,
            "candidate": candidate, "clicked": clicked,
            "input_t": round(input_elapsed, 4) if input_elapsed is not None else None,
            "detector_score": round(detector_score, 4),
        }
        if telemetry is not None:
            entry.update(telemetry)
        self.frames.append(entry)

    def close(self, *, stop_reason: str, tap_count: int,
              candidate_count: int, error: str | None,
              round_started_t: float | None = None,
              input_times: list[float] | None = None,
              menu_actions: list[dict] | None = None) -> Path:
        self._closed = True
        try:
            self._queue.put(None, timeout=2)
        except queue.Full:
            self._error = self._error or RuntimeError('Encoder drain timeout')
        self._worker.join(timeout=10)
        complete = not self._worker.is_alive() and self._error is None and self.written == len(self.frames)
        if complete and self.written:
            verification = cv2.VideoCapture(str(self.path))
            complete = verification.isOpened() and int(verification.get(cv2.CAP_PROP_FRAME_COUNT)) == self.written
            verification.release()
        if not complete:
            error = error or str(self._error or 'Incomplete encoded video')
            stop_reason = 'recording_error'
        live = [r for r in self.frames if r.get('phase') == 'round']
        intervals = np.diff([r['t'] for r in live])
        intervals = intervals[intervals > 0]
        performance = {
            'actual_round_fps': float(1/np.mean(intervals)) if len(intervals) else None,
            'frame_interval_p95_ms': float(np.percentile(intervals, 95)*1000) if len(intervals) else None,
            'encode_median_ms': float(np.median(self.encode_ms)) if self.encode_ms else None,
            'encode_p95_ms': float(np.percentile(self.encode_ms, 95)) if self.encode_ms else None,
            'encode_max_ms': float(max(self.encode_ms)) if self.encode_ms else None,
            'queue_capacity': self._memory_capacity,
            'queue_peak': self.queue_peak,
            'memory_queue_peak': self.memory_peak,
            'spill_capacity_frames': self._spill_capacity,
            'spill_peak_frames': self.spill_peak,
            'spilled_frames': self.spilled_frames,
            'spill_write_max_ms': max(self.spill_write_ms) if self.spill_write_ms else None,
            'retained_spool': str(self._spool_dir) if self._spool_dir is not None and not complete else None,
            'duplicate_measurements': sum(bool(r.get('duplicate_frame')) for r in live),
            'scene_reacquisitions': sum(r.get('decision') == 'scene_cut_reacquire' for r in live),
        }
        duration = live[-1]['t']-live[0]['t'] if len(live) > 1 else 0
        performance['fresh_detection_fps'] = (sum(r.get('detector_ms') is not None and
                                                  not r.get('duplicate_frame', False)
                                                  for r in live)/duration if duration > 0 else None)
        self.performance = performance
        for key in ('capture_ms', 'gate_ms', 'detector_ms', 'fresh_capture_ms', 'input_delay_ms'):
            values = [r[key] for r in live if r.get(key) is not None]
            if values:
                performance[key] = {'median': float(np.median(values)), 'p95': float(np.percentile(values, 95))}
        log_path = self.path.with_suffix(".events.json")
        log_path.write_text(json.dumps({
            "video": str(self.path.resolve()),
            "video_fps": self.fps,
            "capture_target_fps": self.fps,
            "video_size": self.size,
            "video_frame_mapping": "frames[N] = MP4 frame N; no duplicated or interpolated frames",
            "encoding_complete": complete,
            "written_video_frames": self.written,
            "performance": performance,
            "stop_reason": stop_reason,
            "tap_count": tap_count,
            "candidate_count": candidate_count,
            "error": error,
            "round_started_t": round(round_started_t, 4) if round_started_t is not None else None,
            "input_times": input_times if input_times is not None else [],
            "menu_actions": menu_actions if menu_actions is not None else [],
            "frames": self.frames,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if not complete:
            raise RuntimeError(f'錄影未完整完成，已停止批量：{error}')
        if self._spool_dir is not None:
            # Only our successfully drained, now empty spool is removed.
            self._spool_dir.rmdir()
        return log_path
