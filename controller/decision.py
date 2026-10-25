from dataclasses import dataclass

@dataclass(frozen=True)
class BoxDecision:
    jump: bool
    reason: str
    capture_ns: int
    valid_until_ns: int | None
    ready: bool=False
    player_state: str='unknown'
    mode: str='unknown'
    phase: float | None=None
    frequency_hz: float | None=None
    event_in_ms: tuple | None=None
    observation_quality: str='unknown'
    support_width_ms: float | None=None
    note: str='visual event estimate'
