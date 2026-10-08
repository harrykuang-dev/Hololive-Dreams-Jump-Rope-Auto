"""Two independently switchable repairs around frozen V26; visual input only."""
from priority import PriorityDetector

CONFIGS={
    'baseline':{'floor_gap':False,'snap_clock':False},
    'floor_gap':{'floor_gap':True,'snap_clock':False},
    'snap_clock':{'floor_gap':False,'snap_clock':True},
    'both':{'floor_gap':True,'snap_clock':True},
}

class RepairDetector(PriorityDetector):
    def __init__(self, variant):
        super().__init__('speed2')
        config=CONFIGS[variant]
        self.repair_variant=variant
        self.repair_floor_gap=config['floor_gap']
        self.repair_snap_clock=config['snap_clock']

    def telemetry(self):
        return {**super().telemetry(),'repair_variant':self.repair_variant}

def factory(variant):
    if variant not in CONFIGS:
        raise ValueError(variant)
    class Selected(RepairDetector):
        def __init__(self):
            super().__init__(variant)
    return Selected
