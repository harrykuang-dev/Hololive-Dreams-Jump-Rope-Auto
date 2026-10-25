"""Release an arc guard only after observed air and confirmed landing."""
from .floor import FloorLatchPolicy


class LandedUnlockPolicy(FloorLatchPolicy):
    def _update_guard(self,stamp,mode,phase,family,mass,visible,fresh,center=None):
        super()._update_guard(stamp,mode,phase,family,mass,visible,fresh,center)
        self.landing_unlocked=False
        if (not self.armed and family=='arc' and visible and fresh and mass>=.75
            and self.last_down is not None and self.actor.saw_air
            and self.actor.player_state=='grounded'
            and stamp-self.last_down>=self.config['minimum_rejump_ms']*1e6):
            self.armed=True;self.landing_unlocked=True

    def observe(self,*args,**kwargs):
        d=super().observe(*args,**kwargs)
        self.last_diagnostic['confirmed_landing_guard_unlock']=getattr(self,'landing_unlocked',False)
        return d
