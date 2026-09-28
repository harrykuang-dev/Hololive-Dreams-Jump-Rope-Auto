"""Explore geometric event thresholds on saved rope measurements.

This is an offline diagnostic; labels are never used by the game controller.
The later portion is held out when ranking parameter combinations.
"""

import argparse
import itertools
import json
from pathlib import Path


def events_for(samples, coverage, arm, trigger, max_step, below_needed,
               min_contrast=0):
    events = []
    armed = False
    below_count = 0
    previous_height = None
    previous_time = None
    for t, height, confidence, color, line_contrast, *_ in samples:
        if previous_time is not None and not 0 < t - previous_time <= .15:
            armed, below_count, previous_height = False, 0, None
        previous_time = t
        if confidence < coverage:
            armed, below_count, previous_height = False, 0, None
            continue
        if height < arm:
            below_count += 1
            if below_count >= below_needed:
                armed = True
        else:
            below_count = 0
        crossed = (armed and previous_height is not None
                   and previous_height < trigger <= height
                   and height - previous_height <= max_step
                   and line_contrast >= min_contrast)
        previous_height = height
        if crossed:
            events.append(t)
            armed, below_count = False, 0
    return events


def events_for_phase(samples, coverage, arm, trigger, max_step, below_needed,
                     clear_height, clear_needed):
    """Require a visible rope retreat after each candidate, not a timer."""
    events = []
    phase = 'arming'
    below_count = 0
    clear_count = 0
    previous_height = None
    previous_time = None
    for row in samples:
        t, height, confidence = row[:3]
        if previous_time is not None and not 0 < t - previous_time <= .15:
            phase, below_count, clear_count, previous_height = 'arming', 0, 0, None
        previous_time = t
        if confidence < coverage:
            below_count, clear_count, previous_height = 0, 0, None
            continue
        if phase == 'retreat':
            clear_count = clear_count + 1 if height >= clear_height else 0
            if clear_count >= clear_needed:
                phase = 'arming'
                below_count = 0
            previous_height = height
            continue
        below_count = below_count + 1 if height < arm else 0
        if below_count >= below_needed:
            phase = 'armed'
        crossed = (phase == 'armed' and previous_height is not None
                   and previous_height < trigger <= height
                   and height - previous_height <= max_step)
        previous_height = height
        if crossed:
            events.append(t)
            phase, below_count, clear_count = 'retreat', 0, 0
    return events


def score(events, labels, start, end):
    remaining = [t for t in events if start <= t < end]
    true = [t for t in labels if start <= t < end]
    matches = 0
    for label in true:
        possible = [t for t in remaining if -.30 <= t - label <= .10]
        if possible:
            chosen = min(possible, key=lambda t: abs(t - label))
            remaining.remove(chosen)
            matches += 1
    precision = matches / max(1, len([t for t in events if start <= t < end]))
    recall = matches / max(1, len(true))
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return round(f1, 3), matches, len(true), len(remaining)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('replay', type=Path)
    parser.add_argument('labels', type=Path)
    parser.add_argument('--phase', action='store_true',
                        help='sweep visual retreat/rearm state machine')
    args = parser.parse_args()
    samples = json.loads(args.replay.read_text(encoding='utf-8'))['samples']
    labels = json.loads(args.labels.read_text(encoding='utf-8'))['events']
    ranked = []
    if args.phase:
        for params in itertools.product((.12, .18, .24), (-.4, -.3, -.2),
                                        (-.05, 0, .05), (.2, .4, .7), (1, 2),
                                        (0, .05, .1, .15), (1, 2, 3)):
            coverage, arm, trigger, max_step, below_needed, clear_height, clear_needed = params
            if trigger <= arm:
                continue
            events = events_for_phase(samples, *params)
            train = score(events, labels, 16, 80)
            holdout = score(events, labels, 80, 153)
            ranked.append((train, holdout, params))
        ranked.sort(key=lambda item: item[0][0], reverse=True)
        for train, holdout, params in ranked[:20]:
            print(f'train={train} holdout={holdout} params={params}')
        return
    for params in itertools.product((.12, .18, .24, .30, .35),
                                    (-.4, -.3, -.2, -.1),
                                    (-.05, 0, .05, .1, .15),
                                    (.2, .4, .7, 1.0), (1, 2, 3),
                                    (0, .03, .06, .1, .15)):
        coverage, arm, trigger, max_step, below_needed, min_contrast = params
        if trigger <= arm:
            continue
        events = events_for(samples, *params)
        train = score(events, labels, 16, 80)
        holdout = score(events, labels, 80, 153)
        ranked.append((train, holdout, params))
    ranked.sort(key=lambda item: item[0][0], reverse=True)
    for train, holdout, params in ranked[:20]:
        print(f'train={train} holdout={holdout} params={params}')


if __name__ == '__main__':
    main()
