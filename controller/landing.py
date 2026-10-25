"""Small isolated fixes for crossing unlock, landing grace and coherent floor evidence."""
from dataclasses import replace
import numpy as np
from .phase import RepairPhasePolicy
from .speed import speed_lead_ms
from .actor_landing import LandingPlayer

class LandingTimingPolicy(RepairPhasePolicy):
    def __init__(self,name,config):
        super().__init__(name,config)
        self.actor=LandingPlayer(config)

    def _clear_belief(self):
        super()._clear_belief()
        self.ready_since=None;self.was_ready=False;self.floor_track=None;self.last_reliable_ns=None

    def mark_loss(self,stamp):
        super().mark_loss(stamp)
        self.ready_since=None;self.was_ready=False;self.floor_track=None;self.last_reliable_ns=None
        self.guard_previous=None;self.passage_seen=False

    def observe(self,frame,stamp,shape,*,now_ns=None):
        d=super().observe(frame,stamp,shape,now_ns=now_ns)
        now=stamp if now_ns is None else now_ns
        if d.reason in ('noncausal_frame','expired_frame'):
            self.ready_since=None;self.was_ready=False;self.floor_track=None
            return d
        if d.ready and not self.was_ready:self.ready_since=stamp
        self.was_ready=d.ready
        diag=self.last_diagnostic
        family=diag.get('family')
        if (diag.get('used_current_observation') and d.observation_quality=='visible'
            and diag.get('family_mass',0)>=.9 and d.support_width_ms is not None and d.support_width_ms<=80):
            self.last_reliable_ns=stamp
        carry=bool(d.reason=='no_supported_observation' and d.observation_quality=='unobserved'
            and self.last_reliable_ns is not None and 0<=now-self.last_reliable_ns<=80_000_000
            and d.ready and self.armed and diag.get('family_mass',0)>=.9
            and diag.get('motion_range',0)>=diag.get('motion_minimum',1))
        # Update temporal evidence even while airborne, but never act before
        # the original freshness, actor, movement and ambiguity gates pass.
        if family=='floor' and d.observation_quality=='visible' and diag.get('used_current_observation') and diag.get('family_mass',0)>=.9 and (d.valid_until_ns is None or now<=d.valid_until_ns):
            deadline=stamp/1e9+diag['event_center_ms']/1000
            old=self.floor_track
            if old and 0<stamp-old[2]<=100_000_000 and abs(deadline-old[1])<=.040:
                self.floor_track=(old[0],old[1],stamp)
            else:self.floor_track=(stamp,deadline,stamp)
        else:self.floor_track=None
        if d.reason not in ('event_interval_inside_window','event_interval_not_inside_window') and not carry:
            return d
        indices=self.family_indices[family]
        weights=self.weights[indices].ravel();weights=weights/max(1e-20,float(weights.sum()))
        remaining=(self.passage_distance[indices]/self.frequency[indices,None]).ravel()-(now-stamp)/1e9
        base=self.config['floor_lead_ms' if family=='floor' else 'arc_lead_ms']
        lead_ms=speed_lead_ms(base,float(self.frequency[self.mode]),family,self.config)
        lead=lead_ms/1000
        half=self.config['floor_support_half_ms' if family=='floor' else 'air_window_half_ms']/1000
        recent_confirmed_landing=bool(self.config.get('correct_landing_squash',True)
            and self.actor.last_down_ns is not None and self.actor.saw_air
            and self.config['minimum_rejump_ms']*1e6<=stamp-self.actor.last_down_ns<=750_000_000)
        landing_grace=bool(family=='arc' and ((self.ready_since is not None and stamp-self.ready_since<=80_000_000)
            or recent_confirmed_landing))
        support_lower=max(0.,lead-half-(.04 if landing_grace else 0.))
        mass=float(weights[(remaining>=support_lower)&(remaining<=lead+half)].sum())
        required=self.config.get('action_window_mass',.75)
        coherent=bool(family=='floor' and self.floor_track and stamp-self.floor_track[0]>=60_000_000)
        if coherent:required=self.config.get('coherent_floor_mass',.60)
        lower=max(self.config.get('landing_min_center_ms',25)/1000,lead-.12) if landing_grace else max(.04,lead-.06)
        center=diag['event_center_ms']/1000
        jump=mass>=required and lower<=center<=lead
        diag.update(timing_lead_ms=lead_ms,action_window_mass=mass,required_action_window_mass=required,
            coherent_floor=coherent,landing_grace=landing_grace,trigger_lower_ms=lower*1000,
            bounded_occlusion_carry=carry)
        return replace(d,jump=bool(jump),reason='repair_window_supported' if jump else 'repair_window_not_supported')
