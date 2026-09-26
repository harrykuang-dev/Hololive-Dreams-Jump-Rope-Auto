"""Inspect the recorded button animation as a possible human timing label."""
import argparse
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start', type=float, default=64.8)
p.add_argument('--end', type=float, default=65.8)
a = p.parse_args()
cap = cv2.VideoCapture(a.video)
for i in range(round((a.end-a.start)*20)+1):
    t = a.start+i/20
    cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
    ok, frame = cap.read()
    if not ok:
        break
    small = cv2.resize(frame[286:944,526:1700], (960,540))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv[375:490,750:895], (20,100,180), (42,255,255))
    y,x = np.nonzero(m)
    print(f'{t:.2f} yellow={len(x)} center_y={(y.mean()+375 if len(y) else -1):.1f}')
cap.release()
