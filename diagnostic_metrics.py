"""Small diagnostic summaries; never used by the jump controller."""
import math


def statistics(values):
    values=sorted(float(v) for v in values if isinstance(v,(float,int)) and math.isfinite(v))
    if not values:return dict(samples=0,p50=None,p95=None,maximum=None)
    def percentile(fraction):
        position=(len(values)-1)*fraction
        low=int(position);high=min(low+1,len(values)-1)
        return values[low]+(values[high]-values[low])*(position-low)
    return dict(samples=len(values),p50=percentile(.5),p95=percentile(.95),maximum=values[-1])


def pulse_summary(pulses):
    return dict(count=len(pulses),timings={name:statistics(p.get(name) for p in pulses)
        for name in ('actual_ms','capture_return_to_down_ms','native_down_call_ms','native_up_call_ms')},
        nonpositive_duration=sum(p.get('up',0)<=p.get('down',0) for p in pulses),
        duplicate_frame_ids=len(pulses)-len({p.get('frame_id') for p in pulses}))
