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
    args = parser.parse_args()
    samples = json.loads(args.replay.read_text(encoding='utf-8'))['samples']
    labels = json.loads(args.labels.read_text(encoding='utf-8'))['events']
    ranked = []
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
