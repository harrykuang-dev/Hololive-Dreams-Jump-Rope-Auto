"""Small numeric HUD reader and confirmed per-round score limit; no input."""
from pathlib import Path
import math
import cv2
import numpy as np


class HudScoreReader:
    def __init__(self):
        with np.load(Path(__file__).resolve().parent/'assets/score-digits.npz',allow_pickle=False) as data:
            self.templates={i:np.asarray(data[f'digit_{i}'],bool) for i in range(10)}
        self._all=np.concatenate(list(self.templates.values()))
        self._offsets=np.r_[0,np.cumsum([len(x) for x in self.templates.values()])[:-1]]
        self._pixels=np.count_nonzero(self._all,axis=(1,2))

    def read(self,normalized):
        crop=normalized[45:125,35:175]
        mask=cv2.inRange(cv2.cvtColor(crop,cv2.COLOR_BGR2HSV),(0,0,190),(180,65,255))
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        boxes=sorted((tuple(map(int,s[:4])) for s in stats[1:] if s[3]>=20 and s[4]>=80),key=lambda s:s[0])
        if not 1<=len(boxes)<=3 or min(b[3] for b in boxes)/max(b[3] for b in boxes)<.75:return None
        digits=[]
        for x,y,w,h in boxes:
            piece=cv2.resize(mask[y:y+h,x:x+w],(24,36),interpolation=cv2.INTER_NEAREST)>0
            overlap=np.count_nonzero(self._all&piece,axis=(1,2))
            union=self._pixels+np.count_nonzero(piece)-overlap
            scores=np.maximum.reduceat(overlap/np.maximum(1,union),self._offsets)
            order=np.argsort(scores)
            if scores[order[-1]]<.86 or scores[order[-1]]-scores[order[-2]]<.08:return None
            digits.append(str(order[-1]))
        if len(digits)>1 and digits[0]=='0':return None
        return int(''.join(digits))


class ScoreLimit:
    def __init__(self,target,reader=None):
        if type(target) is not int or not 1<=target<=999:raise ValueError('Invalid score limit')
        self.target=target;self.reader=reader or HudScoreReader()
        self.score=None;self.confirmed_ns=None;self.last_read=None
        self.pending=None;self.matches=0;self.next_sample_ns=0;self.last_stamp=None;self.reached=False
        self.near_limit=False

    def observe(self,normalized,stamp):
        if self.reached or stamp<self.next_sample_ns:return self.reached
        if self.last_stamp is not None and stamp<=self.last_stamp:return False
        self.last_stamp=stamp;value=self.reader.read(normalized);self.last_read=value
        self.near_limit=self.near_limit or (value is not None and value>=self.target-3)
        self.next_sample_ns=stamp if self.near_limit else stamp+100_000_000
        if value is None:
            self.pending=None;self.matches=0;return False
        if self.score is not None:
            maximum_step=max(2,math.ceil((stamp-self.confirmed_ns)/1e9*6))
            if value<self.score or value-self.score>maximum_step:
                self.pending=None;self.matches=0;return False
        self.matches=self.matches+1 if value==self.pending else 1;self.pending=value
        if self.matches>=2:
            self.score=value;self.confirmed_ns=stamp
            self.reached=value>=self.target
        return self.reached
