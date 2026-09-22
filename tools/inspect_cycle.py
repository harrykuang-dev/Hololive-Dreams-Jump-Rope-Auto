"""Render a rope rotation from the supplied recording, without live input."""
import argparse
from pathlib import Path
import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('video')
parser.add_argument('--start', type=float, default=47)
parser.add_argument('--step', type=float, default=0.1)
args = parser.parse_args()
cap = cv2.VideoCapture(args.video)
tiles = []
for i in range(16):
    t = args.start + i * args.step
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(t)
    tile = cv2.resize(frame[286:944, 526:1700], (480, 270))
    cv2.putText(tile, f'{t:.2f}', (160, 20), cv2.FONT_HERSHEY_SIMPLEX, .6, (0,0,255), 2)
    tiles.append(tile)
out = Path(__file__).resolve().parents[1] / 'debug' / f'cycle-{args.start}.jpg'
out.parent.mkdir(exist_ok=True)
cv2.imwrite(str(out), np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,16,4)]))
cap.release()
print(out)
