import math

def speed_lead_ms(base, frequency, family, config):
    """Shorten only the arc lead at fast estimated passage rates, without waiting."""
    if family != 'arc' or not math.isfinite(frequency) or frequency <= 0:
        return float(base)
    interval = 1000.0 / frequency
    reduction = min(config.get('speed_max_later_ms', 60.0),
        max(0.0, (config.get('speed_reference_interval_ms', 800.0)-interval)
            * config.get('speed_later_ms_per_interval_ms', .25)))
    return float(base-reduction)
