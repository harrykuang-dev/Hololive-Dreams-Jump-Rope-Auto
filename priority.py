"""Independent priority candidates; every non-control starts with unchanged fix2."""
from collections import deque
import math
import numpy as np
import cv2
import candidates
from candidates import Detector
from candidate_tracker import CandidateTracker

VERSIONS=('v25c','rearm2','speed2','fit2','mode2')
LABELS={'v25c':'V25c同期对照','rearm2':'②原版','speed2':'② + 裁剪后等比例缩放',
        'fit2':'② + 当前高弧确认否决','mode2':'② + 模式几何确认'}
CONFIGS={v:{'width':960,'height':540,'rearm2':v!='v25c','speed':v=='speed2',
            'fit_guard':v=='fit2','mode_guard':v=='mode2'} for v in VERSIONS}
class PriorityTracker(CandidateTracker):
    def __init__(self,name):
        super().__init__(960,540,name in ('fit2','mode2'))
        self.fast=name=='speed2'
        self.last_current_fit=None
    def _solve_triples(self,columns,values):
        return np.linalg.solve(self.basis[columns],values[:,:,None])[:,:,0]
    def _sample_columns(self,frame):
        if not self.fast:return cv2.resize(frame,(self.width,self.height))[:,self.xi]
        source_width=frame.shape[1]
        common=math.gcd(source_width,self.width)
        output_step=self.width//common
        input_step=source_width//common
        left=(int(self.xi.min())//output_step)*output_step
        right=((int(self.xi.max())+1+output_step-1)//output_step)*output_step
        cropped=frame[:,(left//output_step)*input_step:(right//output_step)*input_step]
        return cv2.resize(cropped,(right-left,self.height))[:,self.xi-left]
    def locate(self,frame):
        position=super().locate(frame)
        b=self.segment_support
        self.last_current_fit=None
        if (len(b)==5 and position.coverage>=.4 and position.sag+position.offset<=-.32
                and min(max(b[:2]),max(b[3:]))>=.3):
            self.last_current_fit={'height':position.sag+position.offset,'coverage':position.coverage,'bands':b}
        return position


class PriorityDetector(Detector):
    def __init__(self,name):
        super().__init__('control' if name=='v25c' else 'partial_rearm')
        self.name=name
        self.config=CONFIGS[name]
        self.tracker=PriorityTracker(name)
        self.arc_history=deque(maxlen=12)
        self.floor_geometry=deque(maxlen=8)
        self.fit_veto=False
        self.mode_veto=False
        self.mode_added=False
        candidates.active=self
    def observe(self,frame,now):
        if self.observation_time is not None and not 0<now-self.observation_time<=.15:
            self.arc_history.clear();self.floor_geometry.clear()
        while self.arc_history and now-self.arc_history[0][0]>.10:
            self.arc_history.popleft()
        self.fit_veto=self.mode_veto=self.mode_added=False
        result=super().observe(frame,now)
        current=self.tracker.last_current_fit or self.tracker.far_witness
        if current and not self.tracker.duplicate_frame and not self.tracker.scene_cut:
            self.arc_history.append((now,current['height']))
        if self.tracker.scene_cut:
            self.arc_history.clear();self.floor_geometry.clear()
        return result and not self.fit_veto
    def _high_arc(self):
        w=self.tracker.far_witness
        return bool(w and self.arc_history
                    and self.observation_time-self.arc_history[-1][0]<=.08
                    and abs(w['height']-self.arc_history[-1][1])<=.10)
    def _mark_pass(self,reason):
        p=self.raw_position
        if (self.name=='fit2' and not self.gold_mode
                and reason in ('overhead_approach','occlusion_reappearance')
                and p.coverage<.65 and -.32<=p.sag+p.offset<=.04 and self._high_arc()):
            self.fit_veto=self.vetoed=True
            self.last_reason='current_high_arc_veto'
            return
        super()._mark_pass(reason)
    def _update_gold_mode(self,p,height):
        before=(self.gold_mode,self.armed,self.below_count)
        super()._update_gold_mode(p,height)
        if self.name!='mode2':return
        coefficients=getattr(self.tracker,'coefficients',None)
        if self.context_tick:
            self.floor_geometry.append((height,p.coverage,self._sides(),
                list(map(float,coefficients)) if coefficients is not None else None))
        # Current competing overhead pixels plus the preceding current arc
        # invalidate floor mode; elapsed time alone never manufactures a jump.
        if self._high_arc():
            self.mode_veto=self.gold_mode
            self.gold_mode=False
            self.gold_cycle_primed=False
            self.gold_context_count=0
            self._clear_gold_floor()
            self.shallow_observations.clear()
            w=self.tracker.far_witness
            self.shallow_observations.append((w['height'],w['coverage']))
            if not before[0]:self.armed,self.below_count=before[1:]
            return
        valid=[r for r in self.floor_geometry if -.13<=r[0]<=-.04 and r[1]>=.35 and r[3] is not None]
        if (not self.gold_mode and self.context_tick and len(valid)>=6
                and sum(r[1]>=.45 for r in valid)>=2 and sum(r[2] for r in valid)>=4
                and max(r[0] for r in valid)-min(r[0] for r in valid)>=.015
                and not any(h<-.15 and c>=.35 for h,c,_,_ in self.floor_geometry)):
            curves=np.asarray([r[3] for r in valid])
            if np.ptp(curves[:,0])<=.10 and np.ptp(curves[:,2])<=.08 and np.ptp(curves[:,1]+curves[:,2])<=.08:
                self.gold_mode=self.mode_added=True
                self.armed=True;self.below_count=2
    def telemetry(self):
        return {**super().telemetry(),'candidate_kind':self.name,
                'priority_config':CONFIGS[self.name],'fit_veto':self.fit_veto,
                'mode_veto':self.mode_veto,'mode_added':self.mode_added,
                'arc_history':list(self.arc_history),'floor_geometry':list(self.floor_geometry)}


def factory(name):
    class Selected(PriorityDetector):
        def __init__(self):super().__init__(name)
    return Selected
