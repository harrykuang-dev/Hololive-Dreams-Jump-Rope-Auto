"""Estimate human clicks from the recorded Jump button animation.

Diagnostic only: these labels must not be used as a timing schedule.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start', type=float, default=47)
p.add_argument('--end', type=float, default=155)
p.add_argument('--output', default='debug/button-labels.json')
a = p.parse_args()
cap = cv2.VideoCapture(a.video)
fps = cap.get(cv2.CAP_PROP_FPS)

def mask_at(second):
    cap.set(cv2.CAP_PROP_POS_MSEC, second*1000)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(second)
    client = cv2.resize(frame[286:944,526:1700], (960,540))
    hsv = cv2.cvtColor(client,cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv[380:470,770:875],(20,100,180),(42,255,255))>0

rest = mask_at(47.85)
pressed = mask_at(65.30)
events=[]
was_pressed=False
first,last=round(a.start*fps),round(a.end*fps)
cap.set(cv2.CAP_PROP_POS_FRAMES,first)
for i in range(first,last):
    ok,frame=cap.read()
    if not ok:
        break
    if i%3:
        continue
    client=cv2.resize(frame[286:944,526:1700],(960,540))
    hsv=cv2.cvtColor(client,cv2.COLOR_BGR2HSV)
    current=cv2.inRange(hsv[380:470,770:875],(20,100,180),(42,255,255))>0
    dr=np.count_nonzero(current != rest)
    dp=np.count_nonzero(current != pressed)
    active=dp+100 < dr
    if active and not was_pressed:
        second=i/fps
        # The same animation can re-enter this template for ~0.25s.
        # This de-duplicates benchmark labels only; the bot never reads them.
        if not events or second-events[-1] >= .4:
            events.append(round(second,3))
            print(f'{second:.3f} rest_distance={dr} press_distance={dp}',flush=True)
    was_pressed=active
cap.release()
out=Path(a.output)
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'events':events},indent=2),encoding='utf-8')
print(f'{len(events)} possible human presses; inspect before using as labels')
