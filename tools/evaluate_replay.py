"""Compare offline visual events with independently extracted human presses."""
import argparse
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('candidates',type=Path)
p.add_argument('human',type=Path)
a=p.parse_args()
candidates=json.loads(a.candidates.read_text(encoding='utf-8'))['events']
human=json.loads(a.human.read_text(encoding='utf-8'))['events']
remaining=list(candidates)
matches=[]
misses=[]
for press in human:
    possible=[c for c in remaining if -.30 <= c-press <= .10]
    if possible:
        event=min(possible,key=lambda c:abs(c-press))
        remaining.remove(event)
        matches.append((press,event,round(event-press,3)))
    else:
        misses.append(press)
print(f'human labels={len(human)}, visual events={len(candidates)}, matched={len(matches)}, unmatched events={len(remaining)}')
print(f'candidate timing error, seconds: {[m[2] for m in matches]}')
for start,end in [(47,64),(64,77),(77,91),(91,114),(114,134),(134,155)]:
    labels=[t for t in human if start<=t<end]
    found=[m for m in matches if start<=m[0]<end]
    print(f'{start}-{end}: matched={len(found)}/{len(labels)} missing={[round(t,2) for t in labels if t in misses]}')
print('Unmatched candidate times:',remaining)
