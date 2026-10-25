"""Bounded, continuous visual adjustment of the overhead rope crossing."""

import math

from jump_detector import VisualPassDetector


# The midpoint is the early37 crossing. The right endpoint preserves the
# original release crossing. The two sides have different safe spans, so the
# visual control is continuous but deliberately not a millisecond scale.
DEFAULT_TIMING_POSITION = .5


def validate_timing_position(position):
    if (type(position) not in (int, float) or not math.isfinite(position)
            or not 0 <= position <= 1):
        raise ValueError('Jump timing must be a finite slider position from 0 to 1')
    return float(position)


def threshold_for_position(position):
    position = validate_timing_position(position)
    return round(-.40 + .06*position if position <= .5
                 else -.37 + .18*(position-.5), 6)


def detector_for_timing(position):
    """Keep the release detector intact and add only the earlier crossing."""
    threshold = threshold_for_position(position)
    if threshold == -.28:
        return VisualPassDetector

    class TimedDetector(VisualPassDetector):
        def observe(self, frame, now):
            was_armed = self.armed
            previous_height = self.previous_height
            if super().observe(frame, now):
                return True
            p = self.raw_position
            height = p.sag + p.offset
            bands = self.tracker.segment_support
            if (was_armed and self.armed
                    and not self.gold_mode and not self.blue_rearm_needed
                    and previous_height is not None
                    and previous_height < threshold <= height < -.28
                    and height - previous_height <= .30
                    and p.coverage >= .45 and self.screen_direction == 'down'
                    and len(bands) == 5
                    and min(max(bands[:2]), max(bands[3:])) >= .30
                    and not self.tracker.scene_cut
                    and not self.tracker.duplicate_frame
                    and self.previous_height == height):
                self._mark_pass('early_overhead_approach')
                return not self.vetoed
            return False

    TimedDetector.__name__ = 'TimedVisualDetector'
    return TimedDetector
