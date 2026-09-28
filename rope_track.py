"""Experimental geometric rope tracker. No timer or input injection.

Fits the visible rope between its two holders, then measures its motion.
Outputs are unverified candidate events; the controller independently gates
input to a confirmed live round.
"""
from dataclasses import dataclass
from collections import deque
import cv2
import numpy as np


@dataclass(frozen=True)
class RopePosition:
    sag: float
    coverage: float
    offset: float
    color: str = 'blue'
    contrast: float = 0.


class RopeTracker:
    """Legacy fixed-anchor fit, retained only for offline comparisons."""
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
        gold = cv2.inRange(hsv, (15, 80, 170), (42, 255, 255))
        pink = cv2.inRange(hsv, (140, 65, 150), (179, 255, 255))
        mask = blue | white | gold | pink
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
        line_y = np.clip(yi[best], 0, 539)
        line_x = np.rint(self.x*960).astype(int)
        neighbor_above = mask[np.clip(line_y-7, 0, 539), line_x] > 0
        neighbor_below = mask[np.clip(line_y+7, 0, 539), line_x] > 0
        contrast = scores[best] - .5*(neighbor_above.mean()+neighbor_below.mean())
        color_counts = {
            'blue': np.count_nonzero(blue[line_y, line_x]),
            'gold': np.count_nonzero(gold[line_y, line_x]),
            'pink': np.count_nonzero(pink[line_y, line_x]),
        }
        color = max(color_counts, key=color_counts.get)
        return RopePosition(float(self.candidates[best, 0]), float(scores[best]),
                            float(self.candidates[best, 1]), color, float(contrast))


class SegmentedRopeTracker:
    """Fit thin rope evidence in five image bands with moving rope endpoints.

    Broad moving blue/white props do not count as a thin line. The five bands
    let visible sections constrain the arc when the middle player is obscured.
    No previous jump time or rotation period is used.
    """
    def __init__(self):
        self.previous = None
        self.x = np.linspace(.29, .79, 100)
        self.t = (self.x-.235)/(.84-.235)
        self.basis = np.stack([4*self.t*(1-self.t), self.t, np.ones(100)], axis=1)
        self.xi = np.rint(self.x*960).astype(np.int32)
        self.columns = np.arange(100)
        self.rng = np.random.default_rng(73)
        self.points = None
        self.segment_support = []
        self.coefficients = None
        self.capture_time = None
        self.motion_history = deque(maxlen=12)
        self.duplicate_frame = False
        self.scene_cut = False
        self.previous_coverage = 0.
        self.previous_fit_time = None
        self.geometry_continuity = True
        self.local_refinement = True
        self.appearance_consistency = True
        self.rope_palette = None
        self.palette_time = None
        self.palette_rng = np.random.default_rng(731)
        self.appearance_prior_used = False
        self.player_t = (.565-.235)/.605
        self.player_basis = np.array([4*self.player_t*(1-self.player_t), self.player_t, 1.])
        self.player_reference = .648-.238*self.player_t

    def locate(self, frame):
        self.points = None
        self.segment_support = []
        self.duplicate_frame = False
        self.scene_cut = False
        self.appearance_prior_used = False
        # Only these sampled columns are needed; local line/motion processing
        # is an order of magnitude smaller than processing the entire image.
        frame = cv2.resize(frame, (960, 540))[:, self.xi]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        masks = {
            'blue': cv2.inRange(hsv, (95, 30, 85), (125, 220, 255)),
            'gold': cv2.inRange(hsv, (15, 80, 170), (42, 255, 255)),
            'pink': cv2.inRange(hsv, (140, 65, 150), (179, 255, 255)),
        }
        # Stage lighting darkens blue rope into violet (e.g. H=136,V=71).
        # The old blue V>=85 / pink V>=150 masks excluded the visible line.
        masks['blue'] |= cv2.inRange(hsv, (115, 60, 50), (150, 255, 170))
        mask = masks['blue'] | masks['gold'] | masks['pink'] | cv2.inRange(
            hsv, (0, 0, 195), (180, 50, 255))
        if self.previous is None:
            self.previous = frame
            return RopePosition(0., 0., 0.)
        immediate = cv2.absdiff(frame, self.previous)
        self.duplicate_frame = not np.any(immediate)
        changed = np.max(immediate[20:330], axis=2) > 45
        self.scene_cut = bool(np.all(changed.reshape(310, 5, 20).mean(axis=(0, 2)) > .65))
        baseline = self.previous
        if self.capture_time is not None:
            if self.motion_history and self.capture_time-self.motion_history[-1][0] > .15:
                self.motion_history.clear()
            while len(self.motion_history) > 1 and self.motion_history[1][0] <= self.capture_time-.05:
                self.motion_history.popleft()
            if self.motion_history and self.capture_time-self.motion_history[-1][0] < .04:
                baseline = self.motion_history[0][1]
            self.motion_history.append((self.capture_time, frame))
        motion = np.max(cv2.absdiff(frame, baseline), axis=2) > 18
        self.previous = frame
        if self.scene_cut:
            # Never fit the old scene's motion against a new background.
            self.coefficients = None
            self.previous_coverage = 0.
            self.previous_fit_time = None
            self.rope_palette = None
            self.palette_time = None
            self.motion_history.clear()
            return RopePosition(0., 0., 0.)
        if self.duplicate_frame:
            return RopePosition(0., 0., 0.)
        # Compare channel brightness, not just color membership: the rope may
        # run over a blue backdrop that belongs to the same HSV class.
        pixels = frame.astype(np.int16)
        above = np.concatenate([pixels[:9], pixels[:-9]], axis=0)
        below = np.concatenate([pixels[9:], pixels[-9:]], axis=0)
        ridge = np.max(np.minimum(pixels-above, pixels-below), axis=2) > 15
        # Night-stage blue rope can be darker than the grass/backdrop.
        # Require a thin valley on both sides and blue hue, not a broad
        # dark moving prop surface. Motion and multi-band geometry still gate it.
        dark_ridge = np.max(np.minimum(above-pixels, below-pixels), axis=2) > 15
        ridge |= dark_ridge & (masks['blue'] > 0)
        thin = cv2.dilate(((mask > 0) & ridge & motion).astype(np.uint8),
                          np.ones((5, 1), np.uint8)) > 0
        # Three separated visible pieces estimate curvature and both moving
        # endpoints. Fixed holder hand heights fail when the arms rotate.
        ys, xs = np.nonzero(thin[20:390])
        ys = (ys+20)/540.
        groups = [np.flatnonzero((xs >= k*20) & (xs < (k+1)*20)) for k in range(5)]
        similar = None
        if (self.appearance_consistency and self.rope_palette is not None
                and self.capture_time is not None and self.palette_time is not None
                and 0 < self.capture_time-self.palette_time <= .5):
            hue, saturation, value = self.rope_palette
            dh = np.abs(hsv[:, :, 0].astype(np.float32)-hue)
            dh = np.minimum(dh, 180-dh)
            similar = ((dh <= 9) & (hsv[:, :, 1] >= max(45, saturation-75))
                       & (np.abs(hsv[:, :, 2].astype(np.float32)-value) <= 60))
            similar = cv2.dilate(similar.astype(np.uint8), np.ones((5, 1), np.uint8)) > 0
            palette_points = similar[np.rint(ys*540).astype(int), xs]
            palette_groups = [g[palette_points[g]] for g in groups]
        trials = []
        for a in range(3):
            for b in range(a+1, 4):
                for c in range(b+1, 5):
                    if not all(len(groups[k]) for k in (a, b, c)):
                        continue
                    picks = np.stack([self.rng.choice(groups[k], 160) for k in (a, b, c)], axis=1)
                    column_indices = xs[picks]
                    # Near-identical x values make a quadratic ill-conditioned.
                    keep = np.min(np.diff(column_indices, axis=1), axis=1) >= 8
                    column_indices, picks = column_indices[keep], picks[keep]
                    if len(picks):
                        matrices = self.basis[column_indices]
                        trials.append(np.linalg.solve(matrices, ys[picks, None])[..., 0])
                    if similar is not None and all(len(palette_groups[k]) for k in (a, b, c)):
                        picks = np.stack([self.palette_rng.choice(palette_groups[k], 60)
                                          for k in (a, b, c)], axis=1)
                        column_indices = xs[picks]
                        keep = np.min(np.diff(column_indices, axis=1), axis=1) >= 8
                        column_indices, picks = column_indices[keep], picks[keep]
                        if len(picks):
                            trials.append(np.linalg.solve(self.basis[column_indices], ys[picks, None])[..., 0])
        if self.coefficients is not None:
            trials.append(self.coefficients[None, :])
            if self.local_refinement:
                # A partly occluded arc may have too few lucky three-band
                # random samples. Fit CURRENT ridge pixels near the previous
                # curve with several curvature seeds. No hidden extrapolation:
                # proposals are scored with exactly the same current support.
                seeds = self.coefficients + np.array(
                    [[sag, 0., offset] for sag in (-.12, -.06, 0., .06, .12)
                     for offset in (-.015, 0., .015)])
                for seed in seeds:
                    for _ in range(2):
                        residual = np.abs(ys-self.basis[xs] @ seed)
                        near = residual < .014
                        if np.count_nonzero(near) < 12 or np.ptp(xs[near]) < 40:
                            break
                        seed = np.linalg.lstsq(self.basis[xs[near]], ys[near], rcond=None)[0]
                    else:
                        trials.append(seed[None, :])
        if not trials:
            return RopePosition(0., 0., 0.)
        coefficients = np.vstack(trials)
        left, right = coefficients[:, 2], coefficients[:, 1]+coefficients[:, 2]
        plausible = ((left >= .46) & (left <= .72) & (right >= .30) & (right <= .53)
                     & (coefficients[:, 0] >= -.70) & (coefficients[:, 0] <= .25))
        coefficients = coefficients[plausible]
        if not len(coefficients):
            return RopePosition(0., 0., 0.)
        curves = coefficients @ self.basis.T
        yi = np.rint(curves*540).astype(np.int32)
        valid = (yi >= 0) & (yi < 540)
        yi = np.clip(yi, 0, 539)
        samples = thin[yi, self.columns] & valid
        bands = samples.reshape(-1, 5, 20).mean(axis=2)
        # Reward support across at least three separated bands; a single
        # bowl rim or sleeve must not receive full-arc confidence.
        third = np.sort(bands, axis=1)[:, -3]
        scores = .5*samples.mean(axis=1) + .5*third
        if similar is not None and float(scores.max()) < .65:
            self.appearance_prior_used = True
            # Rank occluded alternatives by the rope's recently OBSERVED
            # chroma. White/cyan bowl rims cannot borrow the confidence of
            # the dark-blue rope. A strong new-color arc bypasses this prior.
            matching = (samples & similar[yi, self.columns]).mean(axis=1)
            scores = scores-.5*(samples.mean(axis=1)-matching)
        # Under occlusion, a bowl rim can narrowly outscore the actual line.
        # Rank CURRENT visible candidates against the last reliable geometry,
        # with a bounded penalty. This does not extrapolate a hidden rope or
        # manufacture coverage; strong newly visible arcs still win outright.
        if (self.geometry_continuity and self.coefficients is not None and self.previous_coverage >= .45
                and self.capture_time is not None and self.previous_fit_time is not None
                and 0 < self.capture_time-self.previous_fit_time <= .08
                # Restrict to the near-floor plateau, where a prop jump
                # invents a dip/rebound. A free overhead arc may move much
                # farther and must not be dragged back toward its old fit.
                and .055 <= float(self.coefficients @ self.player_basis)-self.player_reference <= .18
                and float(scores.max()) < .65):
            previous_curve = self.coefficients @ self.basis.T
            distance = np.mean(np.abs(curves-previous_curve), axis=1)
            scores = scores-np.minimum(.12, .8*distance)
        best = int(scores.argmax())
        support = samples[best]
        coverage = .5*float(support.mean()) + .5*float(third[best])
        counts = {name: np.count_nonzero(mask_[yi[best], self.columns] & support)
                  for name, mask_ in masks.items()}
        color = max(counts, key=counts.get)
        self.points = np.stack([self.xi, yi[best]], axis=1)
        self.segment_support = bands[best].tolist()
        self.coefficients = coefficients[best]
        core = support & (mask[yi[best], self.columns] > 0)
        colors = hsv[yi[best], self.columns][core]
        colors = colors[colors[:, 1] >= 60]
        if coverage >= .7 and len(colors) >= 25:
            self.rope_palette = np.median(colors, axis=0)
            self.palette_time = self.capture_time
        self.previous_coverage = coverage
        self.previous_fit_time = self.capture_time
        player_y = float(self.coefficients @ self.player_basis)
        return RopePosition(player_y-self.player_reference, coverage,
                            0., color, float(support.mean()))


class VisualPassDetector:
    """Experimental visual foot-zone crossing detector; no periodic fallback.

    Require the measured moving rope to approach and cross the foot zone.
    Missing evidence invalidates the current pass.
    """
    def __init__(self):
        self.tracker = SegmentedRopeTracker()
        self.armed = False
        self.below_count = 0
        self.missing_count = 0
        self.previous_height = None
        self.last_confident_height = None
        self.partial_height = None
        self.last_time = None
        self.last_score = 0.
        self.position = RopePosition(0., 0., 0.)
        self.raw_position = self.position
        self.gold_high_count = 0
        self.gold_partial_high_count = 0
        self.gold_peak = False
        self.gold_peak_height = None
        self.gold_descent = 0
        self.gold_trough = False
        self.gold_last_height = None
        self.gold_context_count = 0
        self.gold_mode = False
        self.gold_cycle_primed = False
        self.gold_descending_used = False
        self.shallow_observations = deque(maxlen=8)
        self.floor_dip_height = None
        self.floor_rebounded = False
        self.far_observations = deque(maxlen=5)
        self.blue_rearm_needed = False
        self.blue_far_count = 0
        self.blue_saw_exit = False
        self.blue_retreat_steps = 0
        self.blue_retreat_height = None
        self.last_reason = 'waiting'
        self.screen_direction = 'unknown'
        self.last_context_time = None
        self.context_tick = True

    def telemetry(self):
        coefficients = getattr(self.tracker, 'coefficients', None)
        return {
            'rope_bands': [round(v, 3) for v in getattr(self.tracker, 'segment_support', [])],
            'rope_endpoints_y': ([round(float(coefficients[2]), 4),
                                  round(float(coefficients[1]+coefficients[2]), 4)]
                                 if coefficients is not None and self.position.coverage > 0 else None),
            'rope_direction': self.screen_direction,
            'rope_mode': 'shallow_floor' if self.gold_mode else 'overhead',
            'scene_cut': getattr(self.tracker, 'scene_cut', False),
            'duplicate_frame': getattr(self.tracker, 'duplicate_frame', False),
            'decision': self.last_reason,
            'rope_fit_height': round(self.raw_position.sag+self.raw_position.offset, 5),
            'rope_fit_coverage': round(self.raw_position.coverage, 5),
            'rope_color_prior': getattr(self.tracker, 'appearance_prior_used', False),
        }

    def _mark_pass(self, reason):
        self.last_reason = reason
        if self.gold_mode:
            self.gold_cycle_primed = True
        else:
            self.blue_rearm_needed = True
            self.far_observations.clear()
            self.blue_far_count = 0
            self.blue_saw_exit = False
            self.blue_retreat_steps = 0
            self.blue_retreat_height = None
        self.armed = False
        self.below_count = 0

    def _clear_gold_floor(self):
        self.gold_high_count = 0
        self.gold_partial_high_count = 0
        self.gold_peak = False
        self.gold_peak_height = None
        self.gold_descent = 0
        self.gold_trough = False
        self.gold_last_height = None
        self.floor_dip_height = None
        self.floor_rebounded = False

    def _update_gold_mode(self, p, height):
        # Night-stage floor rope is blue, not gold. A sustained shallow
        # trajectory establishes the same mode without any costume/hue key.
        if self.context_tick:
            self.shallow_observations.append((height, p.coverage))
        shallow = [h for h, c in self.shallow_observations
                   if c >= .45 and .055 <= h <= .18]
        shallow_far = [h for h, c in self.shallow_observations
                       if c >= .45 and -.13 <= h <= -.04]
        sustained_near = len(shallow) >= 6 and max(shallow)-min(shallow) >= .025
        sustained_far = len(shallow_far) >= 6 and max(shallow_far)-min(shallow_far) >= .015
        if ((sustained_near or sustained_far)
                and not any(c >= .35 and h < -.15
                            for h, c in self.shallow_observations)):
            if not self.gold_mode and sustained_far:
                # These already observed far-side samples are also arming
                # evidence. Waiting for two *new* far frames can miss the
                # crossing immediately after blue floor mode is recognized.
                self.armed = True
                self.below_count = 2
            if not self.gold_mode and sustained_near:
                # Mode recognition can happen just after the high point.
                # Preserve that *observed* peak instead of requiring a new
                # one, which otherwise drops the first blue floor swing.
                self.gold_high_count = sum(h >= .12 for h in shallow)
                self.gold_peak = self.gold_high_count >= 2
                if self.gold_peak:
                    self.gold_peak_height = max(shallow)
            self.gold_mode = True
        # Bright ground rope often alternates blue/white/gold labels while
        # staying shallow. Two strong gold observations establish its visual
        # mode; a confidently visible overhead arc ends it regardless of color.
        recent_overhead = any(c >= .35 and h < -.15 for h, c in self.shallow_observations)
        if (p.color == 'gold' and p.coverage >= .5
                and -.12 <= height <= .18 and not recent_overhead):
            if self.context_tick:
                self.gold_context_count += 1
            if self.gold_context_count >= 2:
                self.gold_mode = True
                if (self.gold_context_count == 2 and height < -.04
                        and self.last_confident_height is not None
                        and self.last_confident_height < -.04):
                    self.armed = True
                    self.below_count = 2
        else:
            self.gold_context_count = 0
        if p.coverage >= .35 and height < -.2:
            self.gold_mode = False
            self.gold_cycle_primed = False
            self.gold_context_count = 0
            self.gold_descending_used = False
            self.shallow_observations.clear()
            # Retain the visible overhead evidence when resetting floor mode.
            # An empty window made the same arc's gold-tinted near half look
            # like a newly established floor swing at high capture rates.
            # A lone partial prop fit must not block floor reacquisition.
            if p.coverage >= .5:
                self.shallow_observations.append((height, p.coverage))

    def _gold_floor_rebound(self, p, height):
        """One descending pass per observed shallow swing, independent of hue."""
        if p.coverage >= .45 and height < -.04:
            self.gold_descending_used = False
        if self.gold_descending_used:
            return False
        if p.coverage < .35:
            # Weak prop fits must not invent a trough: a 0.27-confidence
            # outlier caused a false rebound in the night-stage recording.
            return False
        if (self.gold_last_height is not None and p.coverage < .65
                and self.gold_last_height-height > .055):
            # A partly covered plateau sometimes snaps onto the bowl rim.
            # Do not let that weak, abrupt dip invent a trough whose return
            # would consume the only descending trigger of this swing.
            return False
        # Floor mode already requires shallow trajectory evidence. The same
        # glowing line can alternate white/blue/gold within a single swing.
        if height >= .12 and p.coverage >= .5:
            self.gold_high_count += 1
            if self.gold_high_count >= 2:
                self.gold_peak = True
        if height >= .12 and p.coverage >= .35 and self.context_tick:
            self.gold_partial_high_count += 1
            if self.gold_partial_high_count >= 3:
                # Three spaced multi-band measurements can preserve a peak
                # behind bowls even when none reaches the .5 strong threshold.
                self.gold_peak = True
        if self.gold_peak:
            self.gold_peak_height = max(self.gold_peak_height or height, height)
        return_descent = False
        if self.gold_peak and self.gold_last_height is not None:
            # The floor rope has a small high-plateau dip and rebound before
            # its real return toward the player. Distinguish the two using
            # observed direction changes, never elapsed time.
            if self.gold_peak_height-height >= .015:
                if self.floor_dip_height is None:
                    self.floor_dip_height = height
                else:
                    self.floor_dip_height = min(self.floor_dip_height, height)
            # A rebound often returns within .015 of the first peak. Do not
            # require it to remain in the dip zone: that discarded the very
            # rise we needed, delaying the second descent until height .095.
            if (self.floor_dip_height is not None
                    and height-self.floor_dip_height >= .008):
                self.floor_rebounded = True
            return_descent = (self.floor_rebounded and
                              self.gold_last_height-height >= .004 and height <= .125)
            if height < self.gold_last_height - .005:
                self.gold_descent += 1
            if (height <= .08 and (self.gold_descent >= 2 or
                    self.gold_peak_height-height >= .06)):
                self.gold_trough = True
        self.gold_last_height = height
        if (self.gold_peak and p.coverage >= .45
                and (return_descent or (self.gold_descent >= 2
                     and self.gold_peak_height-height >= .025 and height <= .095))):
            # Ignore the small dip/rebound near the high plateau. Only a
            # confirmed descent fires; it stays latched until a far retreat.
            self.gold_descending_used = True
            self._clear_gold_floor()
            return True
        if self.gold_trough and height >= .09 and p.coverage >= .45:
            self.gold_descending_used = True
            self._clear_gold_floor()
            return True
        return False

    def observe(self, frame, now):
        previous_position = self.position
        self.tracker.capture_time = now
        self.position = self.tracker.locate(frame)
        self.raw_position = self.position
        p = self.position
        if getattr(self.tracker, 'duplicate_frame', False):
            self.position = previous_position
            self.last_reason = 'duplicate_frame'
            return False
        if getattr(self.tracker, 'scene_cut', False):
            self.armed = False
            self.previous_height = None
            self.last_confident_height = None
            self.below_count = 0
            self.missing_count = 0
            self.partial_height = None
            self.gold_mode = False
            self.gold_context_count = 0
            self.gold_descending_used = False
            self._clear_gold_floor()
            self.shallow_observations.clear()
            self.far_observations.clear()
            self.blue_rearm_needed = True
            self.blue_far_count = 0
            self.blue_saw_exit = False
            self.blue_retreat_steps = 0
            self.blue_retreat_height = None
            self.last_time = now
            self.last_context_time = None
            self.last_reason = 'scene_cut_reacquire'
            return False
        if (self.last_time is not None and 0 < now-self.last_time < .04
                and previous_position.coverage >= .35 and p.coverage < .55
                and abs(p.sag+p.offset-previous_position.sag-previous_position.offset) > .12):
            # A partial prop fit can teleport across the trigger line in one
            # 60 Hz frame. Await fresh consistent geometry, retaining the
            # last accepted position; never extrapolate an input through it.
            self.position = previous_position
            self.last_reason = 'partial_geometry_snap'
            return False
        # Dense captures must not turn a single short prop flash into six
        # independent context samples. Crossings still run on EVERY fresh frame.
        self.context_tick = self.last_context_time is None or now-self.last_context_time >= .045
        if self.context_tick:
            self.last_context_time = now
        self.last_reason = 'tracking'
        self.screen_direction = 'unknown'
        if (self.last_time is not None and 0 < now-self.last_time <= .15
                and p.coverage >= .35 and previous_position.coverage >= .35):
            delta = p.sag+p.offset-previous_position.sag-previous_position.offset
            self.screen_direction = 'down' if delta > .008 else 'up' if delta < -.008 else 'turning'
        self.last_score = p.coverage
        if self.last_time is not None and not 0 < now-self.last_time <= .15:
            self.armed = False
            self.below_count = 0
            self.missing_count = 0
            self.previous_height = None
            self.last_confident_height = None
            self.partial_height = None
            self.gold_context_count = 0
            self.gold_mode = False
            self.gold_cycle_primed = False
            self.gold_descending_used = False
            self.shallow_observations.clear()
            self.far_observations.clear()
            self._clear_gold_floor()
        self.last_time = now
        height = p.sag+p.offset
        self._update_gold_mode(p, height)
        if self.blue_rearm_needed:
            # Retain a short window across partial occlusion, but require
            # three coherent far measurements, two strong and one very
            # strong. Hue is not evidence of a new rotation.
            if self.context_tick:
                self.far_observations.append((height, p.coverage))
            far = [(h, c) for h, c in self.far_observations
                   if h <= -.32 and c >= .28]
            coherent_far = (len(far) >= 3
                            and sum(c >= .35 for _, c in far) >= 2
                            and max(c for _, c in far) >= .5
                            and max(h for h, _ in far)-min(h for h, _ in far) <= .16
                            and not any(c >= .45 and h > -.25
                                        for h, c in self.far_observations))
            # A bright moving prop can make the fitted arc snap from the foot
            # zone to a distant arc and back in two captures. Require a
            # visible far arc or a continuous retreat after the previous pass;
            # elapsed time alone never re-arms the detector. A genuine
            # switch to shallow gold rope has its own separate visual mode.
            if (p.coverage >= .35
                    and height <= -.32):
                if self.context_tick:
                    self.blue_far_count += 1
            else:
                self.blue_far_count = 0
            if p.coverage >= .45 and height >= .02:
                self.blue_saw_exit = True
                self.blue_retreat_steps = 0
                self.blue_retreat_height = height
            elif self.blue_saw_exit and p.coverage >= .35:
                previous = self.blue_retreat_height
                if previous is not None:
                    drop = previous-height
                    if .005 <= drop <= .18:
                        self.blue_retreat_steps += 1
                    elif drop < -.03:
                        self.blue_retreat_steps = 0
                self.blue_retreat_height = height
            smooth_retreat = (self.blue_saw_exit
                              and (height <= -.38 or (height <= -.32 and p.coverage >= .65))
                              and p.coverage >= .35
                              and self.blue_retreat_steps >= 4)
            # A short retreat to -.27 is not enough: two weak bowl/crowd
            # fits can masquerade as an immediate return. Require either a
            # clear far segment or a deeper, continuously observed retreat.
            if self.blue_far_count < 3 and not coherent_far and not smooth_retreat and not self.gold_mode:
                self.last_reason = 'await_visible_retreat'
                self.armed = False
                self.below_count = 0
                self.missing_count = 0
                self.previous_height = None
                self.last_confident_height = None
                self.partial_height = None
                self._clear_gold_floor()
                return False
            if self.blue_far_count >= 3 or coherent_far or smooth_retreat:
                # The three retreat samples themselves are the arming
                # evidence. Preserve them if the next approach is occluded.
                self.armed = True
                self.below_count = 2
                self.last_confident_height = height
                self.previous_height = height
            self.blue_rearm_needed = False
            self.far_observations.clear()
            self.blue_far_count = 0
            self.blue_saw_exit = False
            self.blue_retreat_steps = 0
            self.blue_retreat_height = None
        floor_rebound = self._gold_floor_rebound(p, height) if self.gold_mode else False
        if p.coverage < .35:
            self.last_reason = 'weak_rope_evidence'
            if self.context_tick or self.missing_count == 0:
                self.missing_count += 1
            # A moving fragment can reveal the near-foot approach before the
            # full rope reappears. It needs two rising visual measurements and
            # an earlier, confidently measured far arc; no timed prediction.
            partial_pass = (
                self.armed and self.last_confident_height is not None
                and self.last_confident_height <= -.35
                and self.missing_count <= 5
                and ((p.coverage >= .25 and p.contrast >= .14
                      and -.35 <= height <= .02
                      and self.partial_height is not None
                      and .07 <= height-self.partial_height <= .18
                      and height >= -.18)
                     or (self.missing_count >= 4 and p.coverage >= .30
                         and p.contrast >= .12 and -.16 <= height <= .02))
            )
            if partial_pass:
                self._mark_pass('visible_fragment_approach')
                self.partial_height = None
                self._clear_gold_floor()
                self.previous_height = None
                return True
            self.partial_height = (height if p.coverage >= .25
                                   and p.contrast >= .14 else None)
            if self.missing_count > 5:
                self.armed = False
                self.below_count = 0
                self.last_confident_height = None
                self.partial_height = None
                self._clear_gold_floor()
            self.previous_height = None
            return False
        recovered_blue_pass = (
            not self.gold_mode and self.armed
            and 1 <= self.missing_count <= 5
            and self.last_confident_height is not None
            and self.last_confident_height <= -.28
            and height > self.last_confident_height
            and ((self.missing_count == 1 and -.28 <= height <= .02
                  and height-self.last_confident_height <= .4
                  and p.contrast >= .12)
                 or (self.missing_count >= 2 and -.28 <= height <= .02
                     and p.contrast >= .06))
        )
        recovered_gold_pass = (
            self.gold_mode and self.armed
            and 1 <= self.missing_count <= 2
            and self.last_confident_height is not None
            and self.last_confident_height <= -.04
            and -.03 <= height <= .08
            and p.coverage >= .45 and p.contrast >= .10
        )
        self.missing_count = 0
        self.partial_height = None
        self.last_confident_height = height
        # Both observed misses were late at the foot zone. A shallow gold
        # ground pass crosses earlier than the blue arc. No timed fallback.
        # In the 29-point run a fast blue arc crossed the old zero threshold
        # only shortly before impact. The player's jump animation needs lead.
        # A full overhead arc can look gold under stage lighting or props.
        # Only a confirmed shallow trajectory changes the crossing direction
        # and threshold; a single color label must never delay a normal pass.
        gold_like = self.gold_mode
        threshold = -.03 if gold_like else -.28
        # Gold passes have a shallower measured arc. In the 21-point replay
        # the visible approach was -.095, -.05 before crossing zero; requiring
        # two samples below -.065 dropped that entire pass.
        if height < (-.04 if gold_like else -.15):
            self.below_count += 1
            if self.below_count >= 2:
                self.armed = True
        else:
            self.below_count = 0
        crossed = (self.armed and self.previous_height is not None
                   and (self.previous_height < threshold <= height
                        or (not gold_like and self.previous_height < 0 <= height))
                   # Two observed blue arcs advanced .225 and .265 in one
                   # capture at the first-hit point. Keep the gold limit
                   # tighter because glowing props can mimic its floor line.
                   and height-self.previous_height <= (.30 if not gold_like else .22))
        self.previous_height = height
        if crossed or floor_rebound or recovered_blue_pass or recovered_gold_pass:
            self._mark_pass('gold_floor_turn' if floor_rebound else
                            'occlusion_reappearance' if recovered_blue_pass or recovered_gold_pass else
                            'gold_floor_crossing' if self.gold_mode else 'overhead_approach')
            if crossed or recovered_blue_pass or recovered_gold_pass:
                self._clear_gold_floor()
            return True
        return False
