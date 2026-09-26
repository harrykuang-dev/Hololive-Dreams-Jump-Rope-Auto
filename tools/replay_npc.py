"""Read-only replay of the independent neighbor jump cue."""
import argparse
from pathlib import Path
import sys
import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from npc_track import NpcJumpTracker

p = argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start', type=float, default=47)
p.add_argument('--end', type=float, default=155)
a=p.parse_args()
cap=cv2.VideoCapture(a.video)
fps=cap.get(cv2.CAP_PROP_FPS)
cap.set(cv2.CAP_PROP_POS_FRAMES, round(a.start*fps))
track=NpcJumpTracker()
events=[]
for index in range(round(a.start*fps),round(a.end*fps)):
    ok, frame=cap.read()
    if not ok:
        break
    if index%3:
        continue
    t=index/fps
    if track.observe(frame[286:944,526:1700],t):
        events.append(round(t,3))
        print(f'{t:.3f}',flush=True)
cap.release()
print(f'{len(events)} independent visual events (not a game score)')
