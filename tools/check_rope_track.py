"""Print measured rope geometry on video; never clicks or predicts a period."""
import argparse
from pathlib import Path
import sys
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rope_track import RopeTracker

p = argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start', type=float, default=47)
p.add_argument('--end', type=float, default=49)
a = p.parse_args()
cap = cv2.VideoCapture(a.video)
track = RopeTracker()
for i in range(round((a.end-a.start)*20)+1):
    t = a.start + i/20
    cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(t)
    estimate = track.locate(frame[286:944,526:1700])
    print(f'{t:.2f} sag={estimate.sag:.3f} coverage={estimate.coverage:.2f} offset={estimate.offset:.3f}')
cap.release()
