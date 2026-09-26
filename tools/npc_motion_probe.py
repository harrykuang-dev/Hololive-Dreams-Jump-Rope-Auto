"""Read-only probe of upward motion in neighboring characters."""
import argparse
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start', type=float, default=64.8)
p.add_argument('--end', type=float, default=65.8)
a = p.parse_args()
cap = cv2.VideoCapture(a.video)
prior = None
for i in range(round((a.end-a.start)*20)+1):
    t = a.start+i/20
    cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
    ok, frame = cap.read()
    if not ok:
        break
    gray = cv2.cvtColor(cv2.resize(frame[286:944,526:1700], (960,540)), cv2.COLOR_BGR2GRAY)
    if prior is not None:
        output = []
        for cx,cy in [(350,270),(447,255),(625,230),(710,220)]:
            mask = np.zeros_like(prior)
            cv2.rectangle(mask,(cx-30,cy-35),(cx+30,cy+40),255,-1)
            pts = cv2.goodFeaturesToTrack(prior, 60,.02,4,mask=mask)
            if pts is None:
                output.append('na'); continue
            moved,ok,_ = cv2.calcOpticalFlowPyrLK(prior,gray,pts,None)
            d=(moved-pts).reshape(-1,2)[ok.reshape(-1)>0]
            d=d[np.abs(d[:,0])<8]
            output.append(f'{np.median(d[:,1]):5.1f}' if len(d) else 'na')
        print(f'{t:.2f} {" ".join(output)}')
    prior=gray
cap.release()
