"""Experimental visual cue from neighboring players' jump motion."""
from __future__ import annotations

import cv2
import numpy as np


class NpcJumpTracker:
    """Find simultaneous upward movement; reset only after visible landing."""

    # Centers of four other players in the fixed Unity scene, at 960x540.
    PLAYER_CENTERS = ((350, 270), (447, 255), (625, 230), (710, 220))

    def __init__(self):
        self.previous = None
        self.previous_time = None
        self.airborne = False
        self.last_motion = ()

    def observe(self, frame, now: float) -> bool:
        gray = cv2.cvtColor(cv2.resize(frame, (960, 540)), cv2.COLOR_BGR2GRAY)
        if self.previous is None or self.previous_time is None:
            self.previous, self.previous_time = gray, now
            return False
        dt = now - self.previous_time
        if not 0 < dt <= .15:
            self.previous, self.previous_time = gray, now
            self.airborne = False
            return False
        movements = []
        for cx, cy in self.PLAYER_CENTERS:
            mask = np.zeros_like(gray)
            cv2.rectangle(mask, (cx-30, cy-35), (cx+30, cy+40), 255, -1)
            points = cv2.goodFeaturesToTrack(self.previous, 60, .02, 4, mask=mask)
            if points is None:
                continue
            moved, valid, _ = cv2.calcOpticalFlowPyrLK(self.previous, gray, points, None)
            if moved is None:
                continue
            delta = (moved-points).reshape(-1, 2)[valid.reshape(-1)>0]
            delta = delta[np.abs(delta[:, 0]) < max(8, dt*160)]
            if len(delta) >= 8:
                movements.append(float(np.median(delta[:, 1])*.05/dt))
        self.previous, self.previous_time = gray, now
        self.last_motion = tuple(movements)
        if len(movements) < 2:
            return False
        going_up = sum(value < -8 for value in movements) >= 2
        landing = sum(value > 7 for value in movements) >= 2
        if landing:
            self.airborne = False
        if going_up and not self.airborne:
            self.airborne = True
            return True
        return False
