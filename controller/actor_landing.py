"""Recognize bounded downward landing squash after a confirmed real jump."""
import numpy as np
from .phase import FullFramePlayer

class LandingPlayer(FullFramePlayer):
    def _player(self,marker,shape,now):
        self.landing_squash=False
        if (self.config.get('correct_landing_squash',True) and marker is not None
            and self.ground is not None and self.last_down_ns is not None and self.saw_air):
            h,w=shape;x0,y0,x1,y1=marker
            if np.isfinite(marker).all() and 0<=x0<x1<=w and 0<=y0<y1<=h:
                x,y=(x0+x1)/2/w,(y0+y1)/2/h
                elapsed=(now-self.last_down_ns)/1e6
                same_x=self.last_marker is not None and abs(x-self.last_marker[0])<=self.config['marker_x_jump']
                in_range=self.config['main_x_range'][0]<=x<=self.config['main_x_range'][1]
                delta=y-self.ground
                if (same_x and in_range and self.config['minimum_rejump_ms']<=elapsed<=750
                    and 0<delta<=2.5*self.config['ground_tolerance']):
                    # A descending/squashed body can be LOWER than its standing
                    # reference while feet are grounded. Never clamp upward air.
                    marker=(x0,y0-delta*h,x1,y1-delta*h)
                    self.landing_squash=True
        return super()._player(marker,shape,now)
