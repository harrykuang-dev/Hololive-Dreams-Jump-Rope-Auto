"""Experimental geometric rope tracker. No timer or input injection.

Fits the visible rope between its two holders, then measures its motion.
Outputs are unverified candidate events; the controller independently gates
input and defaults to observation only.
"""
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass(frozen=True)
class RopePosition:
    sag: float
    coverage: float
    offset: float


class RopeTracker:
    def __init__(self):
        self.previous = None
        self.x = np.linspace(.29, .79, 110)
        self.t = (self.x - .235) / (.84 - .235)
        self.sags = np.linspace(-.65, .23, 177)
        self.offsets = np.linspace(-.035, .035, 15)
        sag, offset = np.meshgrid(self.sags, self.offsets)
        self.candidates = np.stack([sag.ravel(), offset.ravel()], axis=1)
        self.y = (.648 - .238 * self.t[None, :]
                  + self.candidates[:, :1] * (4 * self.t * (1-self.t))[None, :]
                  + self.candidates[:, 1:])

    def locate(self, frame):
        frame = cv2.resize(frame, (960, 540))
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, (95, 30, 85), (125, 220, 255))
        white = cv2.inRange(hsv, (0, 0, 195), (180, 50, 255))
        mask = cv2.bitwise_or(blue, white)
        if self.previous is None:
            self.previous = frame
            return RopePosition(0., 0., 0.)
        motion = np.max(cv2.absdiff(frame, self.previous), axis=2) > 25
        self.previous = frame
        mask[~motion] = 0
        mask = cv2.dilate(mask, np.ones((5, 1), np.uint8))
        yi = np.rint(self.y * 540).astype(int)
        valid = (yi >= 0) & (yi < 540)
        samples = (mask[np.clip(yi, 0, 539), np.rint(self.x*960).astype(int)] > 0) & valid
        scores = samples.mean(axis=1)
        best = int(scores.argmax())
        return RopePosition(float(self.candidates[best, 0]), float(scores[best]),
                            float(self.candidates[best, 1]))


class VisualPassDetector:
    """Experimental full-curve reversal detector; no periodic fallback.

    Require visible overhead rope, then visible foreground rope, then a
    measured upward turn. Missing evidence invalidates the current pass.
    """
    def __init__(self):
        self.tracker = RopeTracker()
        self.armed = False
        self.peak = None
        self.last_time = None
        self.last_score = 0.
        self.position = RopePosition(0., 0., 0.)

    def observe(self, frame, now):
        self.position = self.tracker.locate(frame)
        p = self.position
        self.last_score = p.coverage
        if self.last_time is not None and not 0 < now-self.last_time <= .15:
            self.armed = False
            self.peak = None
        self.last_time = now
        if p.coverage < .35:
            self.armed = False
            self.peak = None
            return False
        height = p.sag+p.offset
        if height < -.15:
            self.armed = True
            self.peak = None
        elif self.armed and height >= .07:
            self.peak = max(height, self.peak if self.peak is not None else height)
        if self.armed and self.peak is not None and height < self.peak-.022:
            self.armed = False
            self.peak = None
            return True
        return False
