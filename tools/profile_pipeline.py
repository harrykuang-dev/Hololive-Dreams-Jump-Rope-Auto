"""Offline cadence/latency audit. Does not capture the desktop or send input."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import RoundGate
from rope_track import SegmentedRopeTracker


def stats(values):
    return {'median': round(float(np.median(values)), 3),
            'p95': round(float(np.percentile(values, 95)), 3)} if len(values) else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('events', type=Path, nargs='+')
    p.add_argument('--benchmark', action='store_true')
    args = p.parse_args()
    for path in args.events:
        data = json.loads(path.read_text(encoding='utf-8'))
        rows = [r for r in data['frames'] if r.get('phase') == 'round']
        gaps = np.diff([r['t'] for r in rows])
        result = next((r['t'] for r in data['frames'] if r.get('phase') == 'result'), None)
        print(path.name, json.dumps({
            'round_fps': round(1/float(np.mean(gaps)), 2),
            'interval_ms': stats(gaps*1000),
            'candidate_to_input_ms': stats([(r['input_t']-r['t'])*1000 for r in rows if r.get('input_t') is not None]),
            'inputs_after_result': sum(t >= result for t in data['input_times']) if result else None,
            'menus_after_start': sum(a['t'] >= data['round_started_t'] for a in data['menu_actions']),
            'stop': data['stop_reason'], 'error': data['error'],
        }))
        if args.benchmark:
            cap = cv2.VideoCapture(str(path.with_suffix('').with_suffix('.mp4')))
            costs = {'decode_ms': [], 'gate_ms': [], 'tracker_ms': []}
            tracker = SegmentedRopeTracker()
            for row in data['frames']:
                started = time.perf_counter()
                ok, frame = cap.read()
                decoded = time.perf_counter()
                if not ok:
                    raise RuntimeError('Missing video frame')
                if row.get('phase') != 'round':
                    continue
                costs['decode_ms'].append((decoded-started)*1000)
                RoundGate.gameplay_visible(frame)
                RoundGate.player_ready(frame)
                gated = time.perf_counter()
                tracker.capture_time = row['t']
                tracker.locate(frame)
                costs['gate_ms'].append((gated-decoded)*1000)
                costs['tracker_ms'].append((time.perf_counter()-gated)*1000)
                if len(costs['tracker_ms']) == 600:
                    break
            cap.release()
            print('OFFLINE ONLY (not live capture):', {key: stats(v) for key, v in costs.items()})


if __name__ == '__main__':
    main()
