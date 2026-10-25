"""Observed actor state and actual input history."""
from collections import deque
class JumpController:

    def __init__(self, config):
        self.config = dict(config)
        if self.config['hold_ms'] != 25 or not 0 < self.config['overhead_trigger'] < self.config['floor_entry'] < 1:
            raise ValueError('Invalid control configuration')
        self.reset()

    def reset(self):
        self.last_ns = None
        self.last_received_ns = None
        self.last_marker = None
        self.ground = None
        self.stable = deque(maxlen=30)
        self.last_down_ns = None
        self.saw_air = False
        self.ground_since_ns = None
        self.player_state = 'unknown'
        self._clear_rope()

    def _clear_rope(self):
        self.previous = None
        self.high_count = 0
        self.overhead_armed = False
        self.exit_seen = self.last_down_ns is None
        self.last_high_ns = None
        self.history = deque(maxlen=90)
        self.floor_armed = True
        self.floor_low = 1.0
        self.floor_peak = 0.0
        self.floor_retreat_seen = False

    def commit_jump(self, down_ns):
        if self.last_down_ns is not None and down_ns <= self.last_down_ns:
            raise ValueError('Noncausal input feedback')
        self.last_down_ns = int(down_ns)
        self.saw_air = False
        self.ground_since_ns = None
        self.player_state = 'awaiting_action'
        self.overhead_armed = False
        self.exit_seen = False
        self.high_count = 0
        self.floor_armed = False
        self.floor_low = 1.0
        self.floor_peak = 0.0
        self.floor_retreat_seen = False
