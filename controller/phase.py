"""Causal full-frame motion-template controller. No image, model, wait, or input.

Visible reference passages are not exact physical collision ground truth.
Seg uses whole-frame mask profiles; Detect uses one whole visible-object box.
"""
from collections import deque
from dataclasses import dataclass
import math
import numpy as np
from .state import JumpController
from .decision import BoxDecision

class FullFramePlayer(JumpController):
    def _player(self,marker,shape,now):
        h,w=shape
        if marker is None:
            self.stable.clear();self.ground_since_ns=None;self.player_state='unknown';return False
        x0,y0,x1,y1=marker
        if not np.isfinite(marker).all() or not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('Invalid full-frame marker')
        x,y=(x0+x1)/2/w,(y0+y1)/2/h
        if not self.config['main_x_range'][0]<=x<=self.config['main_x_range'][1]:
            self.ground=None;self.stable.clear();self.ground_since_ns=None;self.player_state='displaced';return False
        if self.last_marker and abs(x-self.last_marker[0])>self.config['marker_x_jump']:
            self.ground=None;self.stable.clear();self.ground_since_ns=None
        self.last_marker=(x,y)
        if self.ground is None:
            self.stable.append((now,y))
            while self.stable and now-self.stable[0][0]>250_000_000:self.stable.popleft()
            values=[p[1] for p in self.stable]
            if len(values)>=3 and np.ptp(values)<=self.config['ground_stable_range'] and now-self.stable[0][0]>=self.config['ground_confirm_ms']*1e6:
                self.ground=float(np.median(values))
            else:self.player_state='locating_ground';return False
        at_ground=abs(y-self.ground)<=self.config['ground_tolerance']
        if self.last_down_ns is not None:
            elapsed=now-self.last_down_ns
            if y<self.ground-self.config['air_displacement']:
                self.saw_air=True;self.player_state='airborne';self.ground_since_ns=None;return False
            if elapsed<self.config['minimum_rejump_ms']*1e6:
                self.player_state='airborne' if self.saw_air else 'awaiting_action';return False
            if not self.saw_air and elapsed<self.config['unconfirmed_action_recovery_ms']*1e6:
                self.player_state='unconfirmed_action';return False
        if not at_ground:
            self.ground_since_ns=None;self.player_state='recovering'
            if self.last_down_ns is None or now-self.last_down_ns>900_000_000:self.ground=None;self.stable.clear()
            return False
        if self.ground_since_ns is None:self.ground_since_ns=now
        ready=now-self.ground_since_ns>=self.config['landing_confirm_ms']*1e6
        self.player_state='grounded' if ready else 'confirming_ground';return ready

class RepairPhasePolicy:
    def __init__(self,name,config):
        self.name=name;self.config=config;self.names=list(config['modes'])
        self.templates=np.array([config['modes'][m]['features'] for m in self.names],float)
        self.sigma=np.array([config['modes'][m]['sigma'] for m in self.names],float)
        self.m,self.n,self.dim=self.templates.shape;self.grid=np.arange(self.n)/self.n
        if self.dim not in (4,7) or not np.isfinite(self.templates).all() or not np.all(self.sigma>0):raise ValueError('Invalid full-frame reference')
        self.initial_frequency=np.array([1/config['modes'][m]['reference_period_s'] for m in self.names])
        self.events=[np.array(config['modes'][m]['event_phases']) for m in self.names]
        self.families=[config['modes'][m]['family'] for m in self.names]
        self.family_indices={f:np.array([i for i,x in enumerate(self.families) if x==f]) for f in set(self.families)}
        self.passage_distance=np.array([np.min((e[:,None]-self.grid[None,:])%1,axis=0) for e in self.events])
        self.actor=FullFramePlayer(config);self.reset()

    @property
    def ground(self):return self.actor.ground
    def _clear_belief(self):
        self.weights=np.full((self.m,self.n),1/(self.m*self.n));self.frequency=self.initial_frequency.copy()
        self.mode=None;self.phase=None;self.last_good=None;self.motion=deque(maxlen=40);self.phase_history=deque(maxlen=20);self.guard_previous=None;self.passage_seen=False
    def reset(self):
        self._clear_belief();self.actor.reset();self.last_ns=None;self.last_down=None;self.armed=True;self.recovery_until=0;self.last_diagnostic={}
    def mark_loss(self,stamp):self.actor.reset();self.recovery_until=int(stamp)+600_000_000
    def invalidate_observation(self):self._clear_belief();self.last_ns=None
    def commit_jump(self,stamp):
        self.actor.commit_jump(stamp);self.last_down=int(stamp);self.armed=False;self.passage_seen=False

    def _update_guard(self,stamp,mode,phase,family,mass,visible,fresh,center=None):
        # Latch a supported crossing WHEN it happens; don't wait 350ms to
        # observe it. Keep the actual minimum input interval separately.
        coordinate=((phase-self.events[mode][0])*len(self.events[mode]))%1
        previous=self.guard_previous
        supported=visible and fresh and mass>=.75
        if supported and previous is not None:
            old_stamp,old_mode,old_coordinate=previous
            step=(coordinate-old_coordinate)%1
            if (old_mode==mode and 0<stamp-old_stamp<=100_000_000
                and old_coordinate>.75 and coordinate<.25 and 0<step<.20
                and self.last_down is not None and stamp>self.last_down):
                self.passage_seen=True
        self.guard_previous=(stamp,mode,coordinate) if supported else None
        fallback=(center is not None and center>(1. if family=='arc' else .5)*.5/self.frequency[mode])
        if (not self.armed and (self.passage_seen or fallback) and self.last_down is not None
            and stamp-self.last_down>self.config['minimum_rejump_ms']*1e6):
            self.armed=True

    def observe(self,frame,stamp,shape,*,now_ns=None):
        stamp=int(stamp);now=stamp if now_ns is None else int(now_ns);expiry=None if self.config['frame_validity_ms'] is None else stamp+int(self.config['frame_validity_ms']*1e6)
        base=dict(capture_ns=stamp,valid_until_ns=expiry)
        if now<stamp or self.last_ns is not None and stamp<=self.last_ns:
            self.invalidate_observation();return BoxDecision(False,'noncausal_frame',**base)
        dt=0. if self.last_ns is None else (stamp-self.last_ns)/1e9
        if dt>self.config['maximum_observation_gap_ms']/1000:self.invalidate_observation();dt=0.
        self.last_ns=stamp
        if dt:
            for i in range(self.m):
                sample=(self.grid-self.frequency[i]*dt)%1
                shifted=np.interp(sample,np.r_[self.grid,1.],np.r_[self.weights[i],self.weights[i,0]])
                mix=min(.18,.02*dt*60)
                self.weights[i]=(1-2*mix)*shifted+mix*np.roll(shifted,1)+mix*np.roll(shifted,-1)
            self.weights=(1-.002)*self.weights+.002/(self.m*self.n);self.weights/=self.weights.sum()
        ready=False if stamp<self.recovery_until else self.actor._player(frame.marker_xyxy,shape,stamp)
        features=np.asarray(frame.features,float)
        if features.shape!=(self.dim,):raise ValueError('Feature geometry differs from calibration')
        valid=np.isfinite(features);used=bool(valid.any());quality='visible'
        if used:
            residual=(self.templates-features[None,None,:])/self.sigma[:,None,:]
            terms=np.minimum(np.nan_to_num(residual)**2,36)
            censored=np.zeros(self.dim,bool)
            # A narrow visible union or frame boundary is a bound, not a
            # hallucinated complete rectangle. Profiles can still contribute.
            if valid[:4].all():
                if features[3]-features[2]<self.config['partial_width_fraction']:censored[:4]=True
                censored[:4]|=[features[0]<.002,features[1]>.998,features[2]<.002,features[3]>.998]
            for j in range(self.dim):
                if not valid[j]:terms[:,:,j]=0
                elif censored[j]:
                    signed=residual[:,:,j] if j in (0,2) else -residual[:,:,j]
                    terms[:,:,j]=np.minimum(np.maximum(signed,0)**2,36)
            cost=terms.sum(2)/max(1,int(valid.sum()))
            # Only earlier observations: the secant distinguishes repeated
            # rectangles on approach/retreat without adding a frame of delay.
            self.motion.append((stamp,features.copy(),valid.copy()))
            while self.motion and stamp-self.motion[0][0]>250_000_000:self.motion.popleft()
            if len(self.motion)>=3:
                ts=np.array([(s-stamp)/1e9 for s,_,_ in self.motion]);span=-ts[0]
                if .04<=span<=.25:
                    values=np.stack([v for _,v,_ in self.motion]);known=np.stack([v for _,_,v in self.motion]).all(0)&~censored
                    centred=ts-ts.mean();observed=(centred[:,None]*(np.nan_to_num(values)-np.nan_to_num(values).mean(0))).sum(0)/max(1e-12,float(centred@centred))
                    position=(np.arange(self.n)[None,:]-self.frequency[:,None]*span*self.n)%self.n
                    lower=np.floor(position).astype(int);alpha=(position-lower)[:,:,None];indices=np.arange(self.m)[:,None]
                    previous=(1-alpha)*self.templates[indices,lower]+alpha*self.templates[indices,(lower+1)%self.n]
                    expected=(self.templates-previous)/span
                    noise=np.maximum(self.sigma[:,None,:]*8,.06)
                    velocity=np.minimum(((expected-observed)/noise)**2,25);velocity[:,:,~known]=0
                    cost+=.35*velocity.sum(2)/max(1,int(known.sum()))
            likelihood=np.exp(-.5*np.minimum(cost,100));weights=self.weights*likelihood
            if weights.sum()<1e-25:weights=likelihood+1e-25
            self.weights=weights/weights.sum();self.last_good=stamp
            if censored.any():quality='partial_visible_bounds'
        else:cost=None;quality='unobserved'
        mode,bin_index=np.unravel_index(self.weights.argmax(),self.weights.shape);phase=bin_index/self.n
        mass=float(self.weights[mode].sum())
        if used:
            if self.mode!=mode:self.phase_history.clear()
            self.phase_history.append((stamp,phase))
            while self.phase_history and stamp-self.phase_history[0][0]>220_000_000:self.phase_history.popleft()
            if len(self.phase_history)>=4 and mass>.65:
                ts=np.array([(s-stamp)/1e9 for s,_ in self.phase_history]);ps=np.unwrap(np.array([p for _,p in self.phase_history])*2*np.pi)/(2*np.pi)
                if np.ptp(ts)>=.065 and np.max(np.abs(np.diff(ps)))<.12:
                    ts-=ts.mean();slope=float(ts@(ps-ps.mean())/max(1e-12,float(ts@ts)))
                    if .15<slope<4 and .4*self.frequency[mode]<slope<2*self.frequency[mode]:
                        gain=min(.12,dt*4);self.frequency[mode]=(1-gain)*self.frequency[mode]+gain*slope
                        scale=self.frequency[mode]/self.initial_frequency[mode]
                        for i in range(self.m):
                            if i!=mode:self.frequency[i]=self.initial_frequency[i]*scale
        self.mode=mode;self.phase=phase;family=self.families[mode];indices=self.family_indices[family]
        family_mass=float(self.weights[indices].sum());prob=self.weights[indices].ravel()/max(family_mass,1e-20)
        times=(self.passage_distance[indices]/self.frequency[indices,None]).ravel();order=np.argsort(times);cdf=np.cumsum(prob[order])
        def q(value):return float(times[order[min(len(order)-1,int(np.searchsorted(cdf,value)))]])
        age=(now-stamp)/1e9;center=q(.5)-age;lo=max(0,q(.05)-.008-age);hi=q(.95)+.008-age
        span=1. if family=='arc' else .5
        self._update_guard(stamp,mode,phase,family,mass,used,(expiry is None or now<=expiry),center)
        movement=0.
        for j in (0,1):
            values=[v[j] for _,v,valid in self.motion if valid[j]]
            if len(values)>=3:movement=max(movement,float(np.ptp(values)))
        minimum=self.config['floor_motion_minimum'] if family=='floor' else self.config['arc_motion_minimum']
        since_good=math.inf if self.last_good is None else (now-self.last_good)/1e6
        base.update(ready=bool(ready),player_state='recovering_after_loss' if stamp<self.recovery_until else self.actor.player_state,
            mode=self.names[mode],phase=float(phase),frequency_hz=float(self.frequency[mode]),
            event_in_ms=(lo*1000,hi*1000),support_width_ms=(hi-lo)*1000,observation_quality=quality)
        self.last_diagnostic={'features':[float(v) if np.isfinite(v) else None for v in features],
            'family':family,'mode_mass':mass,'family_mass':family_mass,'event_center_ms':center*1000,
            'motion_range':movement,'motion_minimum':minimum,'armed':self.armed,'passage_seen_since_down':self.passage_seen,
            'pure_prediction_age_ms':None if not math.isfinite(since_good) else since_good,
            'uses_full_frame':True,'used_current_observation':used,'no_hidden_mask_completion':True}
        reason=None
        if expiry is not None and now>expiry:reason='expired_frame'
        elif frame.marker_xyxy is None:reason='marker_missing'
        elif not used and since_good>self.config['maximum_pure_prediction_ms']:reason='no_supported_observation'
        elif movement<minimum:reason='stationary_or_unobserved_motion'
        elif family_mass<self.config['mode_confidence']:reason='mode_ambiguous'
        elif not ready:reason='player_not_ready'
        elif not self.armed:reason='same_passage_already_pressed'
        lead=self.config['lead_ms']/1000;half=self.config['floor_support_half_ms' if family=='floor' else 'air_window_half_ms']/1000
        jump=reason is None and lead-half<=lo and hi<=lead+half and max(.04,lead-.06)<=center<=lead
        return BoxDecision(bool(jump),reason or ('event_interval_inside_window' if jump else 'event_interval_not_inside_window'),**base)
