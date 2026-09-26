"""Check lineup marker availability throughout the supplied recording."""
import argparse
from pathlib import Path
import sys
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vision import RoundGate

p=argparse.ArgumentParser()
p.add_argument('video')
a=p.parse_args()
cap=cv2.VideoCapture(a.video)
fps=cap.get(cv2.CAP_PROP_FPS)
start,end=round(47*fps),round(155*fps)
cap.set(cv2.CAP_PROP_POS_FRAMES,start)
missing=[]
for index in range(start,end):
    ok,frame=cap.read()
    if not ok:
        raise RuntimeError(index/fps)
    if index%3:
        continue
    if not RoundGate.player_ready(frame[286:944,526:1700]):
        missing.append(round(index/fps,3))
cap.release()
print(f'{len(missing)} missing of {(end-start)//3} sampled frames')
for lo,hi in [(47,98.6),(98.6,102),(102,114),(114,155)]:
    values=[t for t in missing if lo<=t<hi]
    print(f'{lo}-{hi}: {len(values)} missing; first {values[:15]}')
