"""Extract tutorial evidence; never sends input to the game."""
from pathlib import Path
import cv2

video = Path(r'C:\Users\ashel\Videos\NVIDIA\Desktop\Desktop 2026.09.22 - 14.07.58.02.mp4')
out = Path(__file__).resolve().parents[1] / 'debug' / 'rules'
out.mkdir(parents=True, exist_ok=True)
cap = cv2.VideoCapture(str(video))
for t in (9, 12, 14, 17, 20, 23):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if ok:
        cv2.imwrite(str(out / f'{t}.png'), frame[280:944, 526:1700])
cap.release()
