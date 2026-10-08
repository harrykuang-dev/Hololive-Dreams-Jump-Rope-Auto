"""Opt-in diagnostics, encoded off the input thread and packaged between rounds.

Each round has its own <=20 MiB issue attachment. All observations retain their
timestamps/decisions. Dense failure screenshots and selected exact sampled
BGR columns supplement the full trace. Video is deliberately excluded. No network or game assets are used.
"""
from __future__ import annotations

from collections import deque
import gzip
import json
from pathlib import Path
import queue
import threading
import zipfile

import cv2
import numpy as np

ISSUE_LIMIT = 20 * 1024 * 1024
SCREENSHOT_LIMIT = 20  # pairs of raw and annotated frames
JPEG_LIMIT = 96 * 1024


def jpeg_bytes(frame):
    for quality in (85, 75, 65, 50, 35, 20):
        ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok and len(data) <= JPEG_LIMIT:
            return data.tobytes()
    raise RuntimeError('Diagnostic screenshot exceeds its size budget')


class RoundDiagnostics:
    def __init__(self, path, _first_frame, *, fps=60, defer_resize=False):
        self.directory = Path(path).with_suffix('')
        self.directory.mkdir(parents=True, exist_ok=False)
        self.screens = self.directory / 'screenshots'
        self.screens.mkdir()
        self.context_dir = self.directory / 'failure-window'
        self.context_dir.mkdir()
        self.context = {}
        self.context_events = []
        self.archive = self.directory / 'diagnostics.zip'
        self.frames = 0
        self.last_t = 0.
        self.last_shot = -10.
        self.last_state = None
        self.shots = deque()
        self.error = None
        self.performance = {}
        self._queue = queue.Queue(maxsize=32)
        self._queue_bytes = 0
        self.queue_peak = self.queue_bytes_peak = 0
        self._queue_lock = threading.Lock()
        self._thread = threading.Thread(target=self._encode, name='round-diagnostics', daemon=True)
        self._thread.start()

    def check_health(self):
        if self.error:
            raise RuntimeError('Diagnostic recorder failed') from self.error

    def add(self, frame, elapsed, *, telemetry=None, **values):
        self.check_health()
        # Capture owns each returned array. The controller does not modify it;
        # the encoder may safely retain it without a full-screen copy here.
        from candidates import active
        tracker = getattr(active, 'tracker', None)
        columns = getattr(tracker, 'observed_columns', None)
        points = getattr(tracker, 'points', None)
        entry = {'t': round(elapsed, 6), **values, **(telemetry or {})}
        if entry.get('detector_ms') is not None:
            if points is not None:
                entry['rope_points'] = np.asarray(points).tolist()
            columns = columns.copy() if columns is not None else None
        else:
            columns = None
        size = frame.nbytes + (columns.nbytes if columns is not None else 0)
        try:
            with self._queue_lock:
                if self._queue_bytes+size > 128*1024*1024:
                    raise queue.Full
                self._queue.put_nowait((frame, entry, columns))
                self._queue_bytes += size
                self.queue_peak = max(self.queue_peak, self._queue.qsize())
                self.queue_bytes_peak = max(self.queue_bytes_peak, self._queue_bytes)
        except queue.Full as exc:
            # Never block input or silently drop forensic frames.
            raise RuntimeError('Diagnostic encoder cannot keep up; stopped safely') from exc

    def _snapshot(self, frame, entry, columns):
        if any(item[1]['observation'] == entry['observation'] for item in self.shots):
            return
        self.shots.append((frame, entry, columns))
        while len(self.shots) > SCREENSHOT_LIMIT:
            self.shots.popleft()
        self.last_shot = entry['t']

    def _context(self, item):
        self.context[item[1]['observation']] = item
        # Ordered by observation, even when a pre-event window is inserted.
        while len(self.context) > 80:
            del self.context[min(self.context)]

    @staticmethod
    def _markers(frame):
        roi=cv2.cvtColor(frame[95:250,500:600],cv2.COLOR_BGR2HSV)
        yellow=cv2.inRange(roi,(18,110,170),(42,255,255))
        contours,_=cv2.findContours(yellow,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        markers=[]
        for contour in contours:
            area=cv2.contourArea(contour); x,y,w,h=cv2.boundingRect(contour)
            if 22<=area<=110 and 6<=w<=22 and 5<=h<=17:
                markers.append([round((500+x+w/2)/960,5),round((95+y+h/2)/540,5)])
        return markers

    def _encode(self):
        try:
            with gzip.open(self.directory / 'frames.jsonl.gz', 'wt', encoding='utf-8', compresslevel=3) as trace:
                last = None
                history = deque(maxlen=48)
                known_hearts = None
                pending_hearts = None
                confirmations = 0
                context_until = -1.
                while True:
                    item = self._queue.get()
                    if item is None:
                        break
                    frame, entry, columns = item
                    with self._queue_lock:
                        self._queue_bytes -= frame.nbytes + (columns.nbytes if columns is not None else 0)
                    frame = cv2.resize(frame, (960, 540))
                    self.last_t = entry['t']
                    entry['observation'] = self.frames
                    self.frames += 1
                    green = cv2.inRange(cv2.cvtColor(frame[200:222], cv2.COLOR_BGR2HSV), (35, 100, 130), (85, 255, 255))
                    hearts = sum(np.count_nonzero(green[:, x:x+22]) >= 60 for x in (71, 96, 120)) if entry.get('hud') else None
                    entry['hearts'] = int(hearts) if hearts is not None else None
                    entry['player_markers'] = self._markers(frame) if entry.get('hud') else []
                    state = (entry.get('phase'), entry.get('hud'), entry.get('ready'))
                    loss = False
                    if hearts is not None:
                        if known_hearts is None:
                            known_hearts = hearts
                        known_hearts = max(known_hearts, hearts)
                        if hearts < known_hearts:
                            confirmations = confirmations+1 if pending_hearts == hearts else 1
                            pending_hearts = hearts
                            if confirmations >= 3:
                                loss = True
                                known_hearts = hearts
                                confirmations = 0
                        else:
                            confirmations = 0
                            pending_hearts = None
                    ended = entry.get('phase') == 'result' and self.last_state and self.last_state[0] != 'result'
                    if loss or ended:
                        event={'t':entry['t'],'observation':entry['observation'],
                               'reason':'heart_loss' if loss else 'round_end'}
                        self.context_events.append(event)
                        context_until = entry['t']+.25
                        for prior in history:
                            if prior[1]['t'] >= entry['t']-.75:
                                self._context(prior)
                        for offset in (.5, .25, .1):
                            prior=next((p for p in reversed(history) if p[1]['t']<=entry['t']-offset),None)
                            if prior:self._snapshot(*prior)
                    entry['diagnostic_loss'] = loss
                    trace.write(json.dumps(entry, separators=(',', ':'), ensure_ascii=False) + '\n')
                    current=(frame,entry,columns)
                    if entry['t'] <= context_until:
                        self._context(current)
                    important = entry.get('menu_action') or (state != self.last_state and entry['t']-self.last_shot >= .5)
                    if (loss or ended or important or entry['t']-self.last_shot >= 5
                            or (entry.get('candidate') and entry['t']-self.last_shot >= 2)):
                        self._snapshot(*current)
                    self.last_state = state
                    history.append(current)
                    last = current
                if last:
                    self._snapshot(*last)
                self.tail = list(history)
        except Exception as error:
            self.error = error

    def _save_images(self):
        # Encode JPEG and pixel files after input/capture finishes. During play
        # only bounded normalized image references and the trace are retained.
        self.saved_shots=[]
        raw_paths={}
        for frame,entry,columns in self.shots:
            prefix=f"{entry['observation']:06d}"
            raw=self.screens/(prefix+'-raw.jpg')
            annotated=self.screens/(prefix+'-rope.jpg')
            raw.write_bytes(jpeg_bytes(frame))
            overlay=frame.copy()
            pts=np.asarray(entry.get('rope_points',[]),np.int32)
            if len(pts):cv2.polylines(overlay,[pts],False,(255,0,255),2,cv2.LINE_AA)
            label=f"t={entry['t']:.3f} {entry.get('phase')} candidate={entry.get('candidate')} input={entry.get('clicked')}"
            cv2.rectangle(overlay,(0,0),(960,42),(0,0,0),-1)
            cv2.putText(overlay,label,(6,16),cv2.FONT_HERSHEY_SIMPLEX,.44,(255,255,255),1,cv2.LINE_AA)
            cv2.putText(overlay,str(entry.get('decision','')),(6,34),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1,cv2.LINE_AA)
            annotated.write_bytes(jpeg_bytes(overlay))
            files=[raw,annotated]
            if columns is not None:
                pixels=self.screens/(prefix+'-columns.bgr.gz')
                with gzip.open(pixels,'wb',compresslevel=3) as stream:stream.write(columns.tobytes())
                files.append(pixels)
            self.saved_shots.append({'observation':entry['observation'],'t':entry['t'],
                'files':[p.relative_to(self.directory).as_posix() for p in files],
                'columns_shape':list(columns.shape) if columns is not None else None})
            raw_paths[entry['observation']]=raw
        self.saved_context=[]
        for sequence,(frame,entry,_columns) in sorted(self.context.items()):
            raw=raw_paths.get(sequence)
            if raw is None:
                raw=self.context_dir/f'{sequence:06d}.jpg'
                raw.write_bytes(jpeg_bytes(frame))
            self.saved_context.append({'observation':sequence,'t':entry['t'],
                'path':raw.relative_to(self.directory).as_posix()})
        self.shots.clear()
        self.context.clear()

    def close(self, **result):
        # If the worker failed with a full queue, do not wait on that queue.
        while self._thread.is_alive():
            try:
                self._queue.put(None, timeout=.1)
                break
            except queue.Full:
                continue
        self._thread.join(timeout=30)
        if self._thread.is_alive():
            raise RuntimeError('Diagnostic encoder did not finish')
        self.check_health()
        if result.get('stop_reason') != 'round_finished':
            for item in getattr(self,'tail',[]):
                if item[1]['t'] >= self.last_t-.75:
                    self._context(item)
        self._save_images()
        self.tail = []
        self.performance = {'observations': self.frames, 'capture_duration': self.last_t,
                            'queue_peak':self.queue_peak,'queue_bytes_peak':self.queue_bytes_peak,
                            'event_screenshots':len(self.saved_shots), 'failure_frames':len(self.saved_context)}
        self.result = result
        self._write_manifest()

    def _write_manifest(self):
        manifest = {'format_version': 2, 'app_version': '1.0', 'key_down_ms': 25,
                    'video': None, 'result': self.result, 'recording': self.performance,
                    'screenshots':self.saved_shots,'failure_window':self.saved_context,
                    'failure_events':self.context_events,
                    'screenshot_policy':'last 20 raw/rope event pairs + up to 80 dense frames around loss/end (-0.75s,+0.25s); selected exact sampled BGR columns',
                    'archive_limit_bytes': ISSUE_LIMIT}
        (self.directory / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    def package(self, metadata=None, *, limit=ISSUE_LIMIT):
        """Called only after control/capture ends, including on stop/error."""
        if metadata:
            (self.directory / 'performance.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        note=self.directory/'README.txt'
        note.write_text('Attach diagnostics.zip to a GitHub issue. Contains game screenshots; review before sharing. No video.\n'
            'frames.jsonl.gz: every observation as JSON. t is capture time, input_elapsed is mouse-down time; hearts and player_markers are diagnostic estimates only.\n'
            'manifest.json maps observations to dense loss/end screenshots and raw/rope-overlay event pairs. JPEG encoding occurs after control ends.\n'
            'Selected exact sampled columns are gzip BGR uint8; shapes are in manifest.json. All timestamps use the original capture clock.\n'
            'Images are bounded event samples, not every captured frame. No audio, unpacked assets, memory inspection or automatic upload.\n',encoding='utf-8')
        files=[p for p in self.directory.rglob('*') if p.is_file()
               and p != self.archive and not p.name.endswith('.tmp')]
        temporary=self.archive.with_suffix('.zip.tmp')
        self._zip(temporary,files)
        if temporary.stat().st_size>limit:
            raise RuntimeError('Diagnostics exceed the issue budget; originals retained')
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:raise RuntimeError('Diagnostic ZIP verification failed')
        temporary.replace(self.archive)
        return self.archive

    def _zip(self, path, files):
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in sorted(files):
                archive.write(file, file.relative_to(self.directory).as_posix(),
                              compress_type=zipfile.ZIP_STORED if file.suffix in ('.jpg', '.gz') else zipfile.ZIP_DEFLATED)
