"""Inspect whether NPC motion and visible rope jointly cover human jumps."""
import argparse
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('trace',type=Path)
p.add_argument('human',type=Path)
a=p.parse_args()
rows=json.loads(a.trace.read_text(encoding='utf-8'))
human=json.loads(a.human.read_text(encoding='utf-8'))['events']

def stats(name,events):
    unused=list(events)
    match=[]
    for press in human:
        near=[e for e in unused if -.30<=e-press<=.10]
        if near:
            e=min(near,key=lambda e:abs(e-press))
            unused.remove(e)
            match.append(press)
    print(name,'events',len(events),'matched',len(match),'unmatched',len(unused))
    for lo,hi in [(47,64),(64,77),(77,91),(91,114),(114,134),(134,155)]:
        expected=sum(lo<=h<hi for h in human)
        found=sum(lo<=h<hi for h in match)
        print(f' {lo}-{hi}: {found}/{expected}',end='')
    print()

base=[r for r in rows if r[5]]
for name,subset in [
    ('NPC',base),
    ('NPC+ropeCov35',[r for r in base if r[2]>=.35]),
    ('NPC+ropeCov35+foot',[r for r in base if r[2]>=.35 and r[1]>=-.10]),
    ('NPC+ropeCov50+foot',[r for r in base if r[2]>=.50 and r[1]>=-.10]),
]:
    stats(name,[r[0] for r in subset])
