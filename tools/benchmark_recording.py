"""Paced offline encoder benchmark; no desktop access and no game inputs."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from round_recording import RoundRecorder

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('video', type=Path)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
if a.output.exists() or a.output.with_suffix('.events.json').exists():
    raise SystemExit('Do not overwrite an existing recording')
cap = cv2.VideoCapture(str(a.video))
cap.set(cv2.CAP_PROP_POS_FRAMES, 300)
ok, frame = cap.read()
if not ok:
    raise SystemExit('Cannot decode source')
recorder = RoundRecorder(a.output, frame, fps=60)
started = time.perf_counter()
try:
    for i in range(180):
        if i:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Missing source frame')
        delay = started+i/60-time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        recorder.add(frame, time.perf_counter()-started, hud=True, ready=True,
                     candidate=False, clicked=False, detector_score=0,
                     telemetry={'phase': 'round', 'offline_encoder_benchmark': True})
finally:
    cap.release()
    recorder.close(stop_reason='offline_benchmark', tap_count=0,
                   candidate_count=0, error=None, input_times=[])
print(json.dumps(recorder.performance))
