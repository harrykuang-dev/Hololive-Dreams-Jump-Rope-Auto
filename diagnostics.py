"""Bounded per-round images and observations for one session-wide diagnostic."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from contextlib import nullcontext
from pathlib import Path
import queue
import threading
from session_diagnostics import SessionDiagnostics, ISSUE_LIMIT

import cv2
import numpy as np

SCREENSHOT_LIMIT = 20  # pairs of raw and annotated frames
JPEG_LIMIT = 96 * 1024


def jpeg_bytes(frame):
    for quality in (85, 75, 65, 50, 35, 20):
        ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok and len(data) <= JPEG_LIMIT:
            return data.tobytes()
    raise RuntimeError('Diagnostic screenshot exceeds its size budget')


class RoundDiagnostics:
    def __init__(self, path, _first_frame, *, fps=60, defer_resize=False, session=None, round_index=1):
        self.directory = Path(path).with_suffix('')
        self.directory.mkdir(parents=True, exist_ok=False)
        self.screens = self.directory / 'screenshots'
        self.screens.mkdir()
        self.context_dir = self.directory / 'failure-window'
        self.context_dir.mkdir()
        self.context = {}
        self.context_events = []
        self.owns_session = session is None
        self.session = session or SessionDiagnostics(self.directory, {'app_version':'1.3.2'})
        self.round_index = round_index
        self.archive = self.session.archive
        self.frames = 0
        self.last_t = 0.
        self.last_shot = -10.
        self.last_state = None
        self.shots = deque()
        self.error = None
        self.performance = {}
        self._inputs = queue.SimpleQueue()
        self._samples = defaultdict(lambda: deque(maxlen=10000))
        self._reasons = Counter()
        self._counts = Counter()
        self._previous_capture = self._first_capture = self._last_capture = None
        self._queue = queue.Queue(maxsize=32)
        self._queue_bytes = 0
        self.queue_peak = self.queue_bytes_peak = 0
        self._queue_lock = threading.Lock()
        self._thread = threading.Thread(target=self._encode, name='round-diagnostics', daemon=True)
        self._thread.start()

    def check_health(self):
        self.session.check_health()
        if self.error:
            raise RuntimeError('Diagnostic recorder failed') from self.error

    def input_event(self, command, context, returned, reason=None):
        # The native callback only enqueues scalars; JSON/disk/compression work
        # remains on the diagnostic worker, including the UP timer callback.
        self._inputs.put(dict(command=command, frame_id=context['frame_id'],
            capture_ns=context['capture_ns'], native_return_ns=returned,
            native_call_ns=context.get('native_'+command+'_begin_ns'),
            expires_ns=context.get('expires_ns'), reason=reason))

    def _drain_inputs(self):
        while True:
            try:
                entry = self._inputs.get_nowait()
            except queue.Empty:
                return
            self.session.event('native_input', round=self.round_index, **entry)

    def _record_observation(self, entry):
        self._drain_inputs()
        if entry.get('phase') == 'round':
            self._counts['game_observations'] += 1
            for key, condition in (('rope_detected', entry.get('rope_xyxy') is not None),
                                   ('marker_detected', entry.get('marker_xyxy') is not None),
                                   ('ready', entry.get('ready')), ('candidates', entry.get('candidate')),
                                   ('clicked', entry.get('clicked'))):
                self._counts[key] += bool(condition)
            self._reasons[entry.get('decision') or 'unknown'] += 1
            stamp = entry.get('capture_ns')
            if stamp is not None:
                if self._first_capture is None:
                    self._first_capture = stamp
                self._last_capture = stamp
                if self._previous_capture is not None:
                    gap = (stamp-self._previous_capture)/1e6
                    self._samples['observation_gap_ms'].append(gap)
                    for limit in (60, 100, 250):
                        self._counts[f'gaps_over_{limit}ms'] += gap > limit
                self._previous_capture = stamp
            for key in ('capture_ms', 'model_ms', 'control_ms', 'capture_return_to_decision_ms'):
                if isinstance(entry.get(key), (float, int)):
                    self._samples[key].append(entry[key])
            for key, value in entry.get('model_timings_ms', {}).items():
                if isinstance(value, (float, int)):
                    self._samples['model_'+key].append(value)
        self.session.event('observation', trace=True, round=self.round_index, **entry)

    def add(self, frame, elapsed, *, telemetry=None, **values):
        self.check_health()
        # Capture owns each returned array. The controller does not modify it;
        # the encoder may safely retain it without a full-screen copy here.
        columns = None
        entry = {'t': round(elapsed, 6), **values, **(telemetry or {})}
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
            with nullcontext():
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
                    self._record_observation(entry)
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
                self._drain_inputs()
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
            self.session.image(raw, jpeg_bytes(frame), priority=1)
            overlay=frame.copy()
            pts=np.asarray(entry.get('rope_points',[]),np.int32)
            if len(pts):cv2.polylines(overlay,[pts],False,(255,0,255),2,cv2.LINE_AA)
            for box, color in ((entry.get('rope_xyxy'), (255,0,255)), (entry.get('marker_xyxy'), (0,220,255))):
                if box is not None:
                    x0,y0,x1,y1=box
                    cv2.rectangle(overlay,(round(x0),round(y0)),(round(x1),round(y1)),color,2)
            label=f"t={entry['t']:.3f} {entry.get('phase')} candidate={entry.get('candidate')} input={entry.get('clicked')}"
            cv2.rectangle(overlay,(0,0),(960,42),(0,0,0),-1)
            cv2.putText(overlay,label,(6,16),cv2.FONT_HERSHEY_SIMPLEX,.44,(255,255,255),1,cv2.LINE_AA)
            cv2.putText(overlay,str(entry.get('decision','')),(6,34),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1,cv2.LINE_AA)
            self.session.image(annotated, jpeg_bytes(overlay), priority=1)
            files=[raw,annotated]
            self.saved_shots.append({'observation':entry['observation'],'t':entry['t'],
                'files':[p.relative_to(self.session.directory).as_posix() for p in files],
                'columns_shape':list(columns.shape) if columns is not None else None})
            raw_paths[entry['observation']]=raw
        self.saved_context=[]
        for sequence,(frame,entry,_columns) in sorted(self.context.items()):
            raw=raw_paths.get(sequence)
            if raw is None or not raw.exists():
                raw=self.context_dir/f'{sequence:06d}.jpg'
                self.session.image(raw, jpeg_bytes(frame), priority=2)
            self.saved_context.append({'observation':sequence,'t':entry['t'],
                'path':raw.relative_to(self.session.directory).as_posix()})
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
        duration = ((self._last_capture-self._first_capture)/1e9
                    if self._first_capture is not None and self._last_capture != self._first_capture else 0)
        self.performance.update(counts=dict(self._counts), decision_reasons=dict(self._reasons),
            observed_fps=(self._counts['game_observations']-1)/duration if duration else None,
            timings={key:dict(samples=len(values), p50=float(np.percentile(values,50)),
                p95=float(np.percentile(values,95)),maximum=float(max(values)))
                for key,values in self._samples.items() if values},
            timing_sample_policy='most recent 10000 values per metric; counts cover all observations')
        self.performance['findings'] = []
        if self._counts['gaps_over_100ms']:
            self.performance['findings'].append('observation_gaps_exceed_motion_history_limit')
        if self._counts['game_observations'] and not self._counts['candidates']:
            self.performance['findings'].append('no_jump_proposals; inspect decision_reasons and observation gaps')
        if self._counts['game_observations'] and self._counts['rope_detected'] < self._counts['game_observations']*.8:
            self.performance['findings'].append('frequent_rope_detection_missing')
        if self._counts['game_observations'] and self._counts['marker_detected'] < self._counts['game_observations']*.8:
            self.performance['findings'].append('frequent_player_marker_missing')
        self.result = result
        self._write_manifest()

    def _write_manifest(self):
        manifest = {'app_version': '1.3.2', 'key_down_ms': 25,
                    'video': None, 'result': self.result, 'recording': self.performance,
                    'screenshots':self.saved_shots,'failure_window':self.saved_context,
                    'failure_events':self.context_events,
                    'screenshot_policy':'last 20 raw/rope event pairs + up to 80 frames around loss/end (-0.75s,+0.25s); subject to session image budget',
                    'evidence_limits':'HUD heart loss is diagnostic feedback, not a precise collision timestamp. No video.',
                    'archive_limit_bytes': ISSUE_LIMIT}
        self.session.event('round_diagnostics', round=self.round_index, **manifest)

    def package(self, metadata=None, *, limit=ISSUE_LIMIT):
        """Called only after control/capture ends, including on stop/error."""
        self.session.event('round_metadata', round=self.round_index, metadata=metadata or {})
        if not self.owns_session:
            return None
        self.session.close(stop_reason=self.result.get('stop_reason'))
        return self.session.package(limit=limit)

    def _zip(self, path, files):
        self.session._zip(path, files)
