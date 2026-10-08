from collections import deque
import cv2
import numpy as np
from rope_geometry import RopePosition, VisualPassDetector as BaselineDetector

class CandidateTracker:
    """Fit thin rope evidence in five image bands with moving rope endpoints.

    Broad moving blue/white props do not count as a thin line. The five bands
    let visible sections constrain the arc when the middle player is obscured.
    No previous jump time or rotation period is used.
    """

    def __init__(self, width=960, height=540, side_witness=False):
        self.width, self.height = width, height
        self.side_witness = side_witness
        self.ridge_offset = round(9*height/540)
        self.kernel = round(5*height/540) | 1
        self.roi_top = round(20*height/540)
        self.roi_scene = round(330*height/540)
        self.roi_fit = round(390*height/540)
        self.observed_columns = None
        self.far_witness = None
        self.previous = None
        self.x = np.linspace(0.29, 0.79, 100)
        self.t = (self.x - 0.235) / (0.84 - 0.235)
        self.basis = np.stack([4 * self.t * (1 - self.t), self.t, np.ones(100)], axis=1)
        self.xi = np.rint(self.x * self.width).astype(np.int32)
        self.columns = np.arange(100)
        self.rng = np.random.default_rng(73)
        self.points = None
        self.segment_support = []
        self.coefficients = None
        self.capture_time = None
        self.motion_history = deque(maxlen=12)
        self.duplicate_frame = False
        self.scene_cut = False
        self.previous_coverage = 0.0
        self.previous_fit_time = None
        self.geometry_continuity = True
        self.local_refinement = True
        self.appearance_consistency = True
        self.rope_palette = None
        self.palette_time = None
        self.palette_rng = np.random.default_rng(731)
        self.appearance_prior_used = False
        self.player_t = (0.565 - 0.235) / 0.605
        self.player_basis = np.array([4 * self.player_t * (1 - self.player_t), self.player_t, 1.0])
        self.player_reference = 0.648 - 0.238 * self.player_t

    def locate(self, frame):
        self.points = None
        self.segment_support = []
        self.duplicate_frame = False
        self.scene_cut = False
        self.appearance_prior_used = False
        frame = self._sample_columns(frame)
        self.observed_columns = frame
        self.far_witness = None
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        masks = {'blue': cv2.inRange(hsv, (95, 30, 85), (125, 220, 255)), 'gold': cv2.inRange(hsv, (15, 80, 170), (42, 255, 255)), 'pink': cv2.inRange(hsv, (140, 65, 150), (179, 255, 255))}
        masks['blue'] |= cv2.inRange(hsv, (115, 60, 50), (150, 255, 170))
        mask = masks['blue'] | masks['gold'] | masks['pink'] | cv2.inRange(hsv, (0, 0, 195), (180, 50, 255))
        if self.previous is None:
            self.previous = frame
            return RopePosition(0.0, 0.0, 0.0)
        immediate = cv2.absdiff(frame, self.previous)
        self.duplicate_frame = not np.any(immediate)
        changed = np.max(immediate[self.roi_top:self.roi_scene], axis=2) > 45
        self.scene_cut = bool(np.all(changed.reshape(self.roi_scene-self.roi_top, 5, 20).mean(axis=(0, 2)) > 0.65))
        baseline = self.previous
        if self.capture_time is not None:
            if self.motion_history and self.capture_time - self.motion_history[-1][0] > 0.15:
                self.motion_history.clear()
            while len(self.motion_history) > 1 and self.motion_history[1][0] <= self.capture_time - 0.05:
                self.motion_history.popleft()
            if self.motion_history and self.capture_time - self.motion_history[-1][0] < 0.04:
                baseline = self.motion_history[0][1]
            self.motion_history.append((self.capture_time, frame))
        motion = np.max(cv2.absdiff(frame, baseline), axis=2) > 18
        self.previous = frame
        if self.scene_cut:
            self.coefficients = None
            self.previous_coverage = 0.0
            self.previous_fit_time = None
            self.rope_palette = None
            self.palette_time = None
            self.motion_history.clear()
            return RopePosition(0.0, 0.0, 0.0)
        if self.duplicate_frame:
            return RopePosition(0.0, 0.0, 0.0)
        pixels = frame.astype(np.int16)
        above = np.concatenate([pixels[:self.ridge_offset], pixels[:-self.ridge_offset]], axis=0)
        below = np.concatenate([pixels[self.ridge_offset:], pixels[-self.ridge_offset:]], axis=0)
        ridge = np.max(np.minimum(pixels - above, pixels - below), axis=2) > 15
        dark_ridge = np.max(np.minimum(above - pixels, below - pixels), axis=2) > 15
        ridge |= dark_ridge & (masks['blue'] > 0)
        thin = cv2.dilate(((mask > 0) & ridge & motion).astype(np.uint8), np.ones((self.kernel, 1), np.uint8)) > 0
        ys, xs = np.nonzero(thin[self.roi_top:self.roi_fit])
        ys = (ys + self.roi_top) / self.height
        groups = [np.flatnonzero((xs >= k * 20) & (xs < (k + 1) * 20)) for k in range(5)]
        similar = None
        if self.appearance_consistency and self.rope_palette is not None and (self.capture_time is not None) and (self.palette_time is not None) and (0 < self.capture_time - self.palette_time <= 0.5):
            hue, saturation, value = self.rope_palette
            dh = np.abs(hsv[:, :, 0].astype(np.float32) - hue)
            dh = np.minimum(dh, 180 - dh)
            similar = (dh <= 9) & (hsv[:, :, 1] >= max(45, saturation - 75)) & (np.abs(hsv[:, :, 2].astype(np.float32) - value) <= 60)
            similar = cv2.dilate(similar.astype(np.uint8), np.ones((self.kernel, 1), np.uint8)) > 0
            palette_points = similar[np.rint(ys * self.height).astype(int), xs]
            palette_groups = [g[palette_points[g]] for g in groups]
        trials = []
        for a in range(3):
            for b in range(a + 1, 4):
                for c in range(b + 1, 5):
                    if not all((len(groups[k]) for k in (a, b, c))):
                        continue
                    picks = np.stack([self.rng.choice(groups[k], 160) for k in (a, b, c)], axis=1)
                    column_indices = xs[picks]
                    keep = np.min(np.diff(column_indices, axis=1), axis=1) >= 8
                    column_indices, picks = (column_indices[keep], picks[keep])
                    if len(picks):
                        matrices = self.basis[column_indices]
                        trials.append(self._solve_triples(column_indices, ys[picks]))
                    if similar is not None and all((len(palette_groups[k]) for k in (a, b, c))):
                        picks = np.stack([self.palette_rng.choice(palette_groups[k], 60) for k in (a, b, c)], axis=1)
                        column_indices = xs[picks]
                        keep = np.min(np.diff(column_indices, axis=1), axis=1) >= 8
                        column_indices, picks = (column_indices[keep], picks[keep])
                        if len(picks):
                            trials.append(self._solve_triples(column_indices, ys[picks]))
        if self.coefficients is not None:
            trials.append(self.coefficients[None, :])
            if self.local_refinement:
                seeds = self.coefficients + np.array([[sag, 0.0, offset] for sag in (-0.12, -0.06, 0.0, 0.06, 0.12) for offset in (-0.015, 0.0, 0.015)])
                for seed in seeds:
                    for _ in range(2):
                        residual = np.abs(ys - self.basis[xs] @ seed)
                        near = residual < 0.014
                        if np.count_nonzero(near) < 12 or np.ptp(xs[near]) < 40:
                            break
                        seed = np.linalg.lstsq(self.basis[xs[near]], ys[near], rcond=None)[0]
                    else:
                        trials.append(seed[None, :])
        if not trials:
            return RopePosition(0.0, 0.0, 0.0)
        coefficients = np.vstack(trials)
        left, right = (coefficients[:, 2], coefficients[:, 1] + coefficients[:, 2])
        plausible = (left >= 0.46) & (left <= 0.72) & (right >= 0.3) & (right <= 0.53) & (coefficients[:, 0] >= -0.7) & (coefficients[:, 0] <= 0.25)
        coefficients = coefficients[plausible]
        if not len(coefficients):
            return RopePosition(0.0, 0.0, 0.0)
        curves = coefficients @ self.basis.T
        yi = np.rint(curves * self.height).astype(np.int32)
        valid = (yi >= 0) & (yi < self.height)
        yi = np.clip(yi, 0, self.height-1)
        samples = thin[yi, self.columns] & valid
        bands = samples.reshape(-1, 5, 20).mean(axis=2)
        third = np.sort(bands, axis=1)[:, -3]
        scores = 0.5 * samples.mean(axis=1) + 0.5 * third
        if similar is not None and float(scores.max()) < 0.65:
            self.appearance_prior_used = True
            matching = (samples & similar[yi, self.columns]).mean(axis=1)
            scores = scores - 0.5 * (samples.mean(axis=1) - matching)
        if self.geometry_continuity and self.coefficients is not None and (self.previous_coverage >= 0.45) and (self.capture_time is not None) and (self.previous_fit_time is not None) and (0 < self.capture_time - self.previous_fit_time <= 0.08) and (0.055 <= float(self.coefficients @ self.player_basis) - self.player_reference <= 0.18) and (float(scores.max()) < 0.65):
            previous_curve = self.coefficients @ self.basis.T
            distance = np.mean(np.abs(curves - previous_curve), axis=1)
            scores = scores - np.minimum(0.12, 0.8 * distance)
        best = int(scores.argmax())
        if self.side_witness:
            heights = coefficients @ self.player_basis-self.player_reference
            coverage_all = .5*samples.mean(axis=1)+.5*third
            flank = np.minimum(np.max(bands[:, :2], axis=1), np.max(bands[:, 3:], axis=1))
            eligible = ((heights < -.32) & (heights < heights[best]-.12)
                        & (coverage_all >= max(.35, coverage_all[best]-.10))
                        & (flank >= .30) & (flank >= flank[best]+.05)
                        & (scores >= scores[best]-.12))
            if np.any(eligible):
                indices = np.flatnonzero(eligible)
                witness = indices[np.argmax(scores[indices])]
                self.far_witness = {'height': float(heights[witness]),
                    'coverage': float(coverage_all[witness]), 'bands': bands[witness].tolist()}

        support = samples[best]
        coverage = 0.5 * float(support.mean()) + 0.5 * float(third[best])
        counts = {name: np.count_nonzero(mask_[yi[best], self.columns] & support) for name, mask_ in masks.items()}
        color = max(counts, key=counts.get)
        self.points = np.stack([self.xi, yi[best]], axis=1)
        self.segment_support = bands[best].tolist()
        self.coefficients = coefficients[best]
        core = support & (mask[yi[best], self.columns] > 0)
        colors = hsv[yi[best], self.columns][core]
        colors = colors[colors[:, 1] >= 60]
        if coverage >= 0.7 and len(colors) >= 25:
            self.rope_palette = np.median(colors, axis=0)
            self.palette_time = self.capture_time
        self.previous_coverage = coverage
        self.previous_fit_time = self.capture_time
        player_y = float(self.coefficients @ self.player_basis)
        return RopePosition(player_y - self.player_reference, coverage, 0.0, color, float(support.mean()))

class CandidateDetector(BaselineDetector):
    def __init__(self):
        super().__init__()
        self.repair_floor_gap = False
        self.repair_snap_clock = False
        self._last_actual_observation = None
        self._snap_raw_history = deque(maxlen=3)
        self._floor_gap_anchor = None
        self.floor_gap_recovered = False
        self.repair_floor_crossings = 0
        self.repair_snap_rejections = 0

    def _mark_pass(self, reason):
        self._floor_gap_anchor = None
        super()._mark_pass(reason)

    def _recover_floor_gap(self, p, height, now):
        anchor = self._floor_gap_anchor
        return bool(self.repair_floor_gap and anchor and self.gold_mode and self.armed
                    and 1 <= self.missing_count <= 5
                    and 0 < now-anchor['t'] <= .15
                    and anchor['height'] < -.03 <= height <= .08
                    and 0 < height-anchor['height'] <= .12
                    and p.coverage >= .35 and p.contrast >= .1)

    def _observe_baseline(self, frame, now):
        previous_actual = self._last_actual_observation
        self._last_actual_observation = now
        self.floor_gap_recovered = False
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
            self._floor_gap_anchor = None
            self._snap_raw_history.clear()
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
            self.far_pixels.clear()
            self.blue_rearm_needed = True
            self.blue_far_count = 0
            self.blue_saw_exit = False
            self.blue_retreat_steps = 0
            self.blue_retreat_height = None
            self.last_time = now
            self.last_context_time = None
            self.last_reason = 'scene_cut_reacquire'
            return False
        if previous_actual is not None and not 0 < now-previous_actual <= .15:
            self._snap_raw_history.clear()
        self._snap_raw_history.append((now,p.sag+p.offset,p.coverage,p.contrast))
        original_snap = (self.last_time is not None and 0 < now-self.last_time < .04
                         and previous_position.coverage >= .35 and p.coverage < .55
                         and abs(p.sag+p.offset-previous_position.sag-previous_position.offset) > .12)
        # Preserve the baseline weak-fragment and retreat paths. Only extend
        # its expired check for a partly supported jump toward the player.
        # Three current, smooth approach fits can reacquire real fast motion;
        # the held geometry must not freeze a genuine rope indefinitely.
        history=list(self._snap_raw_history)
        coherent_approach = (len(history)==3
            and all(c>=.35 and contrast>=.1 for _,_,c,contrast in history)
            and all(0<b[0]-a[0]<=.04 and -.002<=b[1]-a[1]<=.18
                    for a,b in zip(history,history[1:]))
            and history[-1][1]-history[0][1]>=.02)
        expired_snap = (self.repair_snap_clock and self.last_time is not None
                        and now-self.last_time >= .04 and previous_actual is not None
                        and 0 < now-previous_actual < .04
                        and previous_position.coverage >= .35 and .35<=p.coverage<.55
                        and p.sag+p.offset-previous_position.sag-previous_position.offset > .12
                        and not coherent_approach)
        if original_snap or expired_snap:
            if expired_snap:
                self.repair_snap_rejections += 1
            self.position = previous_position
            self.last_reason = 'partial_geometry_snap'
            return False
        self.context_tick = self.last_context_time is None or now - self.last_context_time >= 0.045
        if self.context_tick:
            self.last_context_time = now
        self.last_reason = 'tracking'
        self.screen_direction = 'unknown'
        if self.last_time is not None and 0 < now - self.last_time <= 0.15 and (p.coverage >= 0.35) and (previous_position.coverage >= 0.35):
            delta = p.sag + p.offset - previous_position.sag - previous_position.offset
            self.screen_direction = 'down' if delta > 0.008 else 'up' if delta < -0.008 else 'turning'
        self.last_score = p.coverage
        if self.last_time is not None and (not 0 < now - self.last_time <= 0.15):
            self._floor_gap_anchor = None
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
            self.far_pixels.clear()
            self._clear_gold_floor()
        sample_interval = now - self.last_time if self.last_time is not None else float('inf')
        self.last_time = now
        height = p.sag + p.offset
        self._update_gold_mode(p, height)
        if self.repair_floor_gap:
            if not self.gold_mode or (self._floor_gap_anchor and now-self._floor_gap_anchor['t'] > .15):
                self._floor_gap_anchor = None
            if self.gold_mode and self.armed and p.coverage >= .35 and p.contrast >= .1 and height < -.03:
                self._floor_gap_anchor = {'t':now, 'height':height}
        extra_retreat = self._partial_retreat(p, height, now)
        if self.blue_rearm_needed:
            self.far_pixels.append((now, height, p.coverage))
            pixel_far = [(t, h, c) for t, h, c in self.far_pixels if h <= -0.32 and c >= 0.28]
            visible_apex = len(pixel_far) >= 3 and pixel_far[-1][0] - pixel_far[0][0] >= 0.045 and (sum((c >= 0.35 for _, _, c in pixel_far)) >= 2) and (max((c for _, _, c in pixel_far)) >= 0.5) and (max((h for _, h, _ in pixel_far)) - min((h for _, h, _ in pixel_far)) <= 0.16) and (not any((c >= 0.45 and h > -0.25 for _, h, c in self.far_pixels)))
            if self.context_tick:
                self.far_observations.append((height, p.coverage))
            far = [(h, c) for h, c in self.far_observations if h <= -0.32 and c >= 0.28]
            coherent_far = len(far) >= 3 and sum((c >= 0.35 for _, c in far)) >= 2 and (max((c for _, c in far)) >= 0.5) and (max((h for h, _ in far)) - min((h for h, _ in far)) <= 0.16) and (not any((c >= 0.45 and h > -0.25 for h, c in self.far_observations)))
            if p.coverage >= 0.35 and height <= -0.32:
                if self.context_tick:
                    self.blue_far_count += 1
            else:
                self.blue_far_count = 0
            if p.coverage >= 0.45 and height >= 0.02:
                self.blue_saw_exit = True
                self.blue_retreat_steps = 0
                self.blue_retreat_height = height
            elif self.blue_saw_exit and p.coverage >= 0.35:
                previous = self.blue_retreat_height
                if previous is not None:
                    drop = previous - height
                    if 0.005 <= drop <= 0.18:
                        self.blue_retreat_steps += 1
                    elif drop < -0.03:
                        self.blue_retreat_steps = 0
                self.blue_retreat_height = height
            smooth_retreat = self.blue_saw_exit and (height <= -0.38 or (height <= -0.32 and p.coverage >= 0.65)) and (p.coverage >= 0.35) and (self.blue_retreat_steps >= 4)
            if self.blue_far_count < 3 and (not coherent_far) and (not visible_apex) and (not smooth_retreat) and (not self.gold_mode) and not extra_retreat:
                self.last_reason = 'await_visible_retreat'
                self.armed = False
                self.below_count = 0
                self.missing_count = 0
                self.previous_height = None
                self.last_confident_height = None
                self.partial_height = None
                self._clear_gold_floor()
                return False
            if self.blue_far_count >= 3 or coherent_far or visible_apex or smooth_retreat or extra_retreat:
                self.armed = True
                self.below_count = 2
                self.last_confident_height = height
                self.previous_height = height
            self.blue_rearm_needed = False
            self.far_observations.clear()
            self.far_pixels.clear()
            self.blue_far_count = 0
            self.blue_saw_exit = False
            self.blue_retreat_steps = 0
            self.blue_retreat_height = None
        floor_rebound = self._gold_floor_rebound(p, height, sample_interval) if self.gold_mode else False
        if p.coverage < 0.35:
            self.last_reason = 'weak_rope_evidence'
            if self.context_tick or self.missing_count == 0:
                self.missing_count += 1
            partial_pass = self.armed and self.last_confident_height is not None and (self.last_confident_height <= -0.35) and (self.missing_count <= 5) and (p.coverage >= 0.25 and p.contrast >= 0.14 and (-0.35 <= height <= 0.02) and (self.partial_height is not None) and (self.partial_time is not None) and (0.04 <= now - self.partial_time <= 0.15) and (0.07 <= height - self.partial_height <= 0.18) and (height >= -0.18) or (self.missing_count >= 4 and p.coverage >= 0.3 and (p.contrast >= 0.12) and (-0.16 <= height <= 0.02)))
            if partial_pass:
                self._mark_pass('visible_fragment_approach')
                self.partial_height = None
                self._clear_gold_floor()
                self.previous_height = None
                return True
            self.partial_height = height if p.coverage >= 0.25 and p.contrast >= 0.14 else None
            self.partial_time = now if self.partial_height is not None else None
            if self.missing_count > 5:
                self.armed = False
                self.below_count = 0
                self.last_confident_height = None
                self.partial_height = None
                self._clear_gold_floor()
            self.previous_height = None
            return False
        recovered_blue_pass = not self.gold_mode and self.armed and (1 <= self.missing_count <= 5) and (self.last_confident_height is not None) and (self.last_confident_height <= -0.28) and (height > self.last_confident_height) and (self.missing_count == 1 and -0.28 <= height <= 0.02 and (height - self.last_confident_height <= 0.4) and (p.contrast >= 0.12) or (self.missing_count >= 2 and -0.28 <= height <= 0.02 and (p.contrast >= 0.06)))
        recovered_gold_pass = self.gold_mode and self.armed and (1 <= self.missing_count <= 2) and (self.last_confident_height is not None) and (self.last_confident_height <= -0.04) and (-0.03 <= height <= 0.08) and (p.coverage >= 0.35) and (p.contrast >= 0.1)
        self.floor_gap_recovered = self._recover_floor_gap(p, height, now)
        self.missing_count = 0
        self.partial_height = None
        self.last_confident_height = height
        gold_like = self.gold_mode
        threshold = -0.03 if gold_like else -0.28
        if height < (-0.04 if gold_like else -0.15):
            self.below_count += 1
            if self.below_count >= 2:
                self.armed = True
        else:
            self.below_count = 0
        crossed = self.armed and self.previous_height is not None and (self.previous_height < threshold <= height or (not gold_like and self.previous_height < 0 <= height)) and (height - self.previous_height <= (0.3 if not gold_like else 0.22))
        self.previous_height = height
        if crossed or floor_rebound or recovered_blue_pass or recovered_gold_pass or self.floor_gap_recovered:
            if self.floor_gap_recovered and not (crossed or floor_rebound or recovered_blue_pass or recovered_gold_pass):
                self.repair_floor_crossings += 1
            self._mark_pass('floor_gap_crossing' if self.floor_gap_recovered and not (crossed or floor_rebound or recovered_blue_pass or recovered_gold_pass) else 'gold_floor_turn' if floor_rebound else 'occlusion_reappearance' if recovered_blue_pass or recovered_gold_pass else 'gold_floor_crossing' if self.gold_mode else 'overhead_approach')
            if crossed or recovered_blue_pass or recovered_gold_pass or self.floor_gap_recovered:
                self._clear_gold_floor()
            return True
        return False

    def telemetry(self):
        return {**super().telemetry(), 'repair_floor_gap':self.repair_floor_gap,
                'repair_snap_clock':self.repair_snap_clock,
                'floor_gap_recovered':self.floor_gap_recovered,
                'repair_floor_crossings':self.repair_floor_crossings,
                'repair_snap_rejections':self.repair_snap_rejections}
