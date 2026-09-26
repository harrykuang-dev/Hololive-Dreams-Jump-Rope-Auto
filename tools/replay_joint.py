"""Read-only synchronized rope and neighboring-player feature trace."""
import argparse
import json
from pathlib import Path
import sys
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from npc_track import NpcJumpTracker
from rope_track import RopeTracker

p=argparse.ArgumentParser()
p.add_argument('video')
p.add_argument('--start',type=float,default=47)
p.add_argument('--end',type=float,default=155)
p.add_argument('--output',type=Path,default=Path('debug/joint.json'))
a=p.parse_args()
cap=cv2.VideoCapture(a.video)
fps=cap.get(cv2.CAP_PROP_FPS)
first,last=round(a.start*fps),round(a.end*fps)
cap.set(cv2.CAP_PROP_POS_FRAMES,first)
rope,npc=RopeTracker(),NpcJumpTracker()
rows=[]
for index in range(first,last):
    ok,frame=cap.read()
    if not ok:
        raise RuntimeError(index/fps)
    if index%3:
        continue
    t=index/fps
    client=frame[286:944,526:1700]
    p=rope.locate(client)
    fired=npc.observe(client,t)
    rows.append([round(t,3),round(p.sag+p.offset,3),round(p.coverage,3),p.color,
                 [round(v,1) for v in npc.last_motion],fired])
cap.release()
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(rows),encoding='utf-8')
print(f'{len(rows)} frames, {sum(row[5] for row in rows)} neighbor events; {a.output}')
