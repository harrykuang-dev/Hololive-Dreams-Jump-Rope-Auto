"""Six independent experiments. Resolution candidates have zero fix flags."""
from collections import deque
from candidate_tracker import CandidateDetector, CandidateTracker

FIXES = ('side_veto', 'partial_rearm', 'shallow_mode')
RESOLUTIONS = ('res720', 'res1080', 'res1440')
VERSIONS = FIXES+RESOLUTIONS
LABELS = {'side_veto':'修复1：高空侧段排除误拟合', 'partial_rearm':'修复2：遮挡后重新武装',
          'shallow_mode':'修复3：浅蓝绳地面模式', 'res720':'识别1280×720',
          'res1080':'识别1920×1080', 'res1440':'识别2560×1440'}
CONFIGS = {k: {'width': 960, 'height': 540, 'fix': k} for k in FIXES}
CONFIGS.update({k: {'width': w, 'height': h, 'fix': None}
                for k,w,h in zip(RESOLUTIONS,(1280,1920,2560),(720,1080,1440))})
CONFIGS['control'] = {'width': 960, 'height': 540, 'fix': None}
active = None


class Detector(CandidateDetector):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.config = CONFIGS[kind]
        self.tracker = CandidateTracker(self.config['width'], self.config['height'], kind=='side_veto')
        self.partial_retreat = deque(maxlen=12)
        self.partial_shallow = deque(maxlen=8)
        self.vetoed = False
        self.extra_retreat = False
        self.observation_time = None
        self.measured_time = None
        global active
        active = self

    def observe(self, frame, now):
        self.input_frame_size = [frame.shape[1], frame.shape[0]]
        if self.observation_time is not None and not 0 < now-self.observation_time <= .15:
            self.partial_retreat.clear()
            self.partial_shallow.clear()
        self.observation_time = now
        self.vetoed = False
        self.extra_retreat = False
        result = self._observe_baseline(frame, now)
        self.measured_time = now
        if self.tracker.scene_cut:
            self.partial_retreat.clear()
            self.partial_shallow.clear()
        return result and not self.vetoed

    def _mark_pass(self, reason):
        p = self.raw_position
        if (self.kind=='side_veto' and not self.gold_mode
                and reason in ('overhead_approach', 'occlusion_reappearance')
                and p.coverage < .65 and -.32 <= p.sag+p.offset <= .04
                and self.tracker.far_witness is not None):
            self.vetoed = True
            self.last_reason = 'side_arc_veto'
            return
        super()._mark_pass(reason)

    def _sides(self):
        b = self.tracker.segment_support
        return len(b)==5 and max(b[:2])>=.25 and max(b[3:])>=.25

    def _partial_retreat(self, p, height, now):
        if self.kind!='partial_rearm':
            return False
        while self.partial_retreat and now-self.partial_retreat[0][0] > .15:
            self.partial_retreat.popleft()
        if not self.blue_rearm_needed or p.coverage < .25 or (p.coverage>=.45 and height>-.25):
            self.partial_retreat.clear()
        current = height<=-.32 and p.coverage>=.35 and p.contrast>=.25 and self._sides()
        if current:
            self.partial_retreat.append((now, height))
        hs = [h for _,h in self.partial_retreat]
        self.extra_retreat = (current and len(hs)>=4 and self.partial_retreat[-1][0]-self.partial_retreat[0][0]>=.06
                              and max(hs)-min(hs)<=.12)
        return self.extra_retreat

    def _update_gold_mode(self, p, height):
        super()._update_gold_mode(p, height)
        if self.kind!='shallow_mode' or not self.context_tick:
            return
        self.partial_shallow.append((height, p.coverage, self._sides()))
        evidence = [(h,c,s) for h,c,s in self.partial_shallow if -.13<=h<=-.04 and c>=.35]
        if (not self.gold_mode and len(evidence)>=6
                and sum(c>=.45 for _,c,_ in evidence)>=2
                and sum(s for _,_,s in evidence)>=3
                and max(h for h,_,_ in evidence)-min(h for h,_,_ in evidence)>=.015
                and not any(h<-.15 and c>=.35 for h,c,_ in self.partial_shallow)):
            self.gold_mode = True
            self.armed = True
            self.below_count = 2

    def telemetry(self):
        return {**super().telemetry(), 'candidate_kind': self.kind,
                'tracker_size': [self.tracker.width,self.tracker.height],
                'input_frame_size': getattr(self, 'input_frame_size', None),
                'far_witness': self.tracker.far_witness,
                'side_veto': self.vetoed, 'partial_retreat_confirmed': self.extra_retreat,
                'partial_retreat_samples': list(self.partial_retreat),
                'partial_shallow_samples': list(self.partial_shallow),
                'armed': self.armed, 'blue_rearm_needed': self.blue_rearm_needed,
                'below_count': self.below_count, 'missing_count': self.missing_count,
                'floor_return_pending': self.floor_return_pending,
                'floor_dip_height': self.floor_dip_height}


def factory(kind):
    class SelectedDetector(Detector):
        def __init__(self):
            super().__init__(kind)
    return SelectedDetector
