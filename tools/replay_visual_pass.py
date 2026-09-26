"""Read-only sequential replay. Events are NOT successful game jumps."""
import argparse
import json
from pathlib import Path
import sys
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rope_track import VisualPassDetector
from vision import RoundGate

p = argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start', type=float, default=47)
p.add_argument('--end', type=float, default=155)
p.add_argument('--output', default='debug/visual-pass.json')
p.add_argument('--crop', nargs=4, type=int, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'),
               default=(526, 286, 1700, 944), help='game client rectangle in video pixels')
a = p.parse_args()
cap = cv2.VideoCapture(a.video)
if not cap.isOpened():
    raise SystemExit(f'Cannot open video: {a.video}')
fps = cap.get(cv2.CAP_PROP_FPS)
if fps <= 0:
    raise SystemExit(f'Cannot read video frame rate: {a.video}')
first, last = round(a.start*fps), round(a.end*fps)
left, top, right, bottom = a.crop
if not (0 <= left < right <= cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        and 0 <= top < bottom <= cap.get(cv2.CAP_PROP_FRAME_HEIGHT)):
    raise SystemExit(f'Invalid crop: {a.crop}')
cap.set(cv2.CAP_PROP_POS_FRAMES, first)
detector = VisualPassDetector()
gate = RoundGate()
events, samples = [], []
for index in range(first, last):
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f'Decode failed at {index/fps}')
    if index % 3:
        continue
    client = frame[top:bottom, left:right]
    allowed = gate.observe(client)
    if gate.finished:
        break
    if not allowed or not RoundGate.player_ready(client):
        continue
    t = index/fps
    fired = detector.observe(client, t)
    pos = detector.position
    samples.append([round(t, 3), round(pos.sag+pos.offset, 3),
                    round(pos.coverage, 3), pos.color, round(pos.contrast, 3), fired])
    if fired:
        events.append(round(t, 3))
        print(f'Visual event {t:.3f}', flush=True)
cap.release()
out = Path(a.output)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({'events': events, 'samples': samples}, indent=2), encoding='utf-8')
print(f'{len(events)} unverified candidate events; not a game score. Output: {out}')
