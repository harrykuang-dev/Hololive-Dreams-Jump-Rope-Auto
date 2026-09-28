"""Extract tutorial evidence; never sends input to the game."""
import argparse
from pathlib import Path
import cv2

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('video', nargs='?', type=Path,
                    default=root / 'recordings' / 'Desktop 2026.09.27 - 03.00.28.01.mp4')
parser.add_argument('--crop', nargs=4, type=int, default=(448, 144, 1773, 889),
                    metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
args = parser.parse_args()
out = root / 'debug' / 'rules'
out.mkdir(parents=True, exist_ok=True)
cap = cv2.VideoCapture(str(args.video))
if not cap.isOpened():
    raise SystemExit(f'Cannot open video: {args.video}')
left, top, right, bottom = args.crop
for t in (9, 12, 14, 17, 20, 23):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if ok:
        cv2.imwrite(str(out / f'{t}.png'), frame[top:bottom, left:right])
cap.release()
