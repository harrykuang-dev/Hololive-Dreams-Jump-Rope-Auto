"""Sequential, read-only source-video HUD validation."""
import argparse
from pathlib import Path
import sys
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import RoundGate

p = argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start', type=float, default=48)
p.add_argument('--end', type=float, default=154)
p.add_argument('--crop', nargs=4, type=int, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'),
               default=(526, 286, 1700, 944))
a = p.parse_args()
cap = cv2.VideoCapture(a.video)
fps = cap.get(cv2.CAP_PROP_FPS)
first, last = round(a.start*fps), round(a.end*fps)
cap.set(cv2.CAP_PROP_POS_FRAMES, first)
left, top, right, bottom = a.crop
bad = []
not_ready = []
for index in range(first, last):
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f'Decode failed at {index/fps}')
    client = frame[top:bottom, left:right]
    if not RoundGate.gameplay_visible(client):
        bad.append(index/fps)
    if not RoundGate.player_ready(client):
        not_ready.append(index/fps)
cap.release()
print(f'Checked {last-first} frames; missing HUD: {len(bad)}')
print('First missing:', bad[:30])
print(f'Player marker not ready: {len(not_ready)}')
print('First not ready:', not_ready[:30])
