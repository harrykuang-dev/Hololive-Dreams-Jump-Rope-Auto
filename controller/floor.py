"""One early, coherent floor passage reservation; arc decisions unchanged."""
from collections import deque
from dataclasses import replace
from .landing import LandingTimingPolicy


class FloorLatchPolicy(LandingTimingPolicy):
    def _clear_belief(self):
        super()._clear_belief()
        self.floor_evidence=deque(maxlen=6)
        self.floor_pending=None
        self.floor_consumed_until=0
        self.floor_good=None
        self.floor_epoch=0

    def mark_loss(self,stamp):
        super().mark_loss(stamp)
        self.floor_evidence.clear();self.floor_pending=None;self.floor_good=None

    def commit_jump(self,stamp):
        super().commit_jump(stamp)
        if self.floor_pending:
            self.floor_consumed_until=self.floor_pending['event_ns']+80_000_000
        else:
            self.floor_consumed_until=stamp+350_000_000
        self.floor_pending=None;self.floor_evidence.clear()

    def observe(self,frame,stamp,shape,*,now_ns=None):
        d=super().observe(frame,stamp,shape,now_ns=now_ns)
        now=stamp if now_ns is None else now_ns
        g=self.last_diagnostic;family=g.get('family')
        if d.reason in ('expired_frame','noncausal_frame'):
            self.floor_pending=None;self.floor_evidence.clear()
            return d
        visible=(family=='floor' and d.observation_quality=='visible'
            and g.get('family_mass',0)>=.9 and g.get('used_current_observation')
            and g.get('motion_range',0)>=g.get('motion_minimum',1))
        if visible:self.floor_good=stamp
        center=g.get('event_center_ms',0)
        if self.floor_pending and (now>self.floor_pending['deadline_ns']+40_000_000
            or self.floor_good is None or now-self.floor_good>180_000_000
            or family!='floor'):
            self.floor_pending=None;self.floor_evidence.clear()
        if visible and now>=self.floor_consumed_until and self.floor_pending is None:
            if 300<=center<=650:
                event=now+int(center*1e6)
                if self.floor_evidence and abs(event-self.floor_evidence[-1][1])>40_000_000:
                    self.floor_evidence.clear()
                self.floor_evidence.append((stamp,event))
                if len(self.floor_evidence)>=4 and stamp-self.floor_evidence[0][0]>=60_000_000:
                    times=sorted(t for _,t in self.floor_evidence)
                    if times[-1]-times[0]<=50_000_000:
                        event=times[len(times)//2];self.floor_epoch+=1
                        self.floor_pending={'id':self.floor_epoch,'event_ns':event,
                            'deadline_ns':event-int(self.config['floor_lead_ms']*1e6)}
            else:self.floor_evidence.clear()
        p=self.floor_pending
        g['floor_reservation']=None if p is None else dict(event_id=p['id'],
            event_after_capture_ms=(p['event_ns']-stamp)/1e6,
            deadline_after_capture_ms=(p['deadline_ns']-stamp)/1e6,
            deadline_lateness_ms=(now-p['deadline_ns'])/1e6)
        if family!='floor' or p is None:return d
        # Original supported opportunity remains usable; reserve cannot remove it.
        due=bool(d.ready and (d.valid_until_ns is None or now<=d.valid_until_ns) and frame.marker_xyxy is not None
            and 0<=now-p['deadline_ns']<=40_000_000 and now>=self.floor_consumed_until)
        return replace(d,jump=bool(d.jump or due),reason='floor_reservation_due' if due else d.reason)
