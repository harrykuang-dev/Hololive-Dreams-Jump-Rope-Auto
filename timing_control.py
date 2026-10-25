"""Continuous time offset around the default event-prediction policy."""
import json,math
from pathlib import Path
DEFAULT_TIMING_POSITION=.5
MAX_OFFSET_MS=40.
def validate_timing_position(position):
    if type(position) not in (int,float) or not math.isfinite(position) or not 0<=position<=1:
        raise ValueError('Jump timing must be a finite slider position from 0 to 1')
    return float(position)
def offset_ms(position):
    # Negative means earlier; positive means later, matching the visible scale.
    return (validate_timing_position(position)-.5)*2*MAX_OFFSET_MS
def control_config(position=DEFAULT_TIMING_POSITION,*,backend=None):
    cfg=json.loads((Path(__file__).resolve().parent/'models/control.json').read_text(encoding='utf-8'))
    cfg['frame_validity_ms']=None
    cfg['native_input_headroom_ms']=0
    delay=offset_ms(position)
    cfg['floor_lead_ms']-=delay;cfg['arc_lead_ms']-=delay
    return cfg
