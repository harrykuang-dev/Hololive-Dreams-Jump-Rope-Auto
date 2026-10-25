"""Add a coherent arc deadline across a bounded detection gap; retain old actions."""
from collections import deque
from dataclasses import replace
from .unlock import LandedUnlockPolicy
from .speed import speed_lead_ms


class ArcCarryPolicy(LandedUnlockPolicy):
    def _clear_belief(self):
        super()._clear_belief()
        self.arc_evidence=deque(maxlen=6);self.arc_pending=None
        self.arc_good=None;self.arc_consumed_until=0;self.arc_epoch=0

    def mark_loss(self,stamp):
        super().mark_loss(stamp)
        self.arc_evidence.clear();self.arc_pending=None;self.arc_good=None

    def commit_jump(self,stamp):
        super().commit_jump(stamp)
        self.arc_consumed_until=(self.arc_pending['event_ns']+80_000_000
                                  if self.arc_pending else stamp+350_000_000)
        self.arc_pending=None;self.arc_evidence.clear()

    def observe(self,frame,stamp,shape,*,now_ns=None):
        d=super().observe(frame,stamp,shape,now_ns=now_ns)
        now=stamp if now_ns is None else now_ns;g=self.last_diagnostic
        if d.reason in ('noncausal_frame','expired_frame') or (d.valid_until_ns is not None and now>d.valid_until_ns):
            self.arc_pending=None;self.arc_evidence.clear();return d
        family=g.get('family')
        reliable=(family=='arc' and d.observation_quality=='visible' and g.get('family_mass',0)>=.9
                  and g.get('mode_mass',0)>=.75 and g.get('used_current_observation')
                  and g.get('motion_range',0)>=g.get('motion_minimum',1))
        if reliable:self.arc_good=stamp
        if self.arc_pending and (family!='arc' or self.arc_good is None
            or now-self.arc_good>180_000_000 or now>self.arc_pending['deadline_ns']+40_000_000):
            self.arc_pending=None;self.arc_evidence.clear()
        center=g.get('event_center_ms',0)
        if reliable and self.arc_pending is None and now>=self.arc_consumed_until:
            if 300<=center<=600:
                event=now+int(center*1e6)
                if self.arc_evidence and abs(event-self.arc_evidence[-1][1])>40_000_000:self.arc_evidence.clear()
                self.arc_evidence.append((stamp,event))
                if len(self.arc_evidence)>=4 and stamp-self.arc_evidence[0][0]>=60_000_000:
                    times=sorted(t for _,t in self.arc_evidence)
                    if times[-1]-times[0]<=40_000_000:
                        event=times[len(times)//2];self.arc_epoch+=1
                        lead=speed_lead_ms(self.config['arc_lead_ms'],d.frequency_hz,'arc',self.config)
                        self.arc_pending={'id':self.arc_epoch,'event_ns':event,'deadline_ns':event-int(lead*1e6)}
            else:self.arc_evidence.clear()
        p=self.arc_pending
        g['arc_reservation']=None if p is None else dict(event_id=p['id'],
            event_after_capture_ms=(p['event_ns']-stamp)/1e6,
            deadline_after_capture_ms=(p['deadline_ns']-stamp)/1e6,
            evidence_age_ms=(stamp-self.arc_good)/1e6)
        if family!='arc' or p is None:return d
        due=bool(d.ready and self.armed and frame.marker_xyxy is not None
            and not g.get('used_current_observation')
            and now>=self.arc_consumed_until and 0<=now-p['deadline_ns']<=40_000_000)
        return replace(d,jump=bool(d.jump or due),reason='arc_reservation_due' if due else d.reason)
