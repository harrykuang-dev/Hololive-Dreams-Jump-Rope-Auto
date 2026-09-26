"""Offline, time-split experiment. Does not save or deploy a learned model."""
import argparse
import json
from pathlib import Path
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier

p=argparse.ArgumentParser()
p.add_argument('trace',type=Path)
p.add_argument('human',type=Path)
a=p.parse_args()
rows=json.loads(a.trace.read_text(encoding='utf-8'))
human=json.loads(a.human.read_text(encoding='utf-8'))['events']

def features(row):
    _,height,coverage,color,motion,fired=row
    values=[height,coverage,float(color=='blue'),float(color=='gold'),float(color=='pink'),
            float(fired),sum(v < -8 for v in motion),sum(v > 7 for v in motion)]
    values.extend((motion+[0.]*4)[:4])
    return values

raw=np.array([features(row) for row in rows],dtype=float)
X=np.array([np.concatenate([raw[max(0,i-j)] for j in range(4)]) for i in range(len(rows))])
times=np.array([row[0] for row in rows])
positive=np.array([any(0<=press-t<=.15 for press in human) for t in times],dtype=int)

def evaluate(events,lo,hi):
    expected=[h for h in human if lo<=h<hi]
    unused=list(events)
    matches=[]
    for press in expected:
        near=[e for e in unused if -.30<=e-press<=.10]
        if near:
            e=min(near,key=lambda e:abs(e-press))
            unused.remove(e)
            matches.append(round(e-press,3))
    return len(matches),len(expected),len(unused),matches,unused

for split in [125.,91.]:
    if split==125.:
        train=(times<split)
        test=(times>=split)
        lo,hi=split,155.
    else:
        # Gold and pink stages are an intentionally difficult withheld block.
        train=(times<64.)|(times>=114.)
        test=(times>=64.)&(times<114.)
        lo,hi=64.,114.
    model=ExtraTreesClassifier(n_estimators=200,min_samples_leaf=3,
                                class_weight='balanced',n_jobs=-1,random_state=42)
    model.fit(X[train],positive[train])
    scores=model.predict_proba(X[test])[:,1]
    test_times=times[test]
    print('Holdout',lo,hi,'train positives',positive[train].sum())
    for threshold in [.2,.3,.4,.5,.6]:
        events=[]
        active=False
        clear=0
        for t,score in zip(test_times,scores):
            above=score>=threshold
            if above and not active:
                events.append(float(t)); active=True; clear=0
            elif not above:
                clear+=1
                if clear>=3:
                    active=False
        result=evaluate(events,lo,hi)
        print(' threshold',threshold,'result',result[:3])
        if threshold==.5:
            print('  unmatched times',[(round(e,2),round(min(human,key=lambda h:abs(h-e))-e,2)) for e in result[4]])
