"""Replay actual recorded pixels on the JSON capture clock; never send input."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rope_track import SegmentedRopeTracker, VisualPassDetector


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('events', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--frames', type=int, nargs='*', default=[])
    p.add_argument('--unregularized', action='store_true', help='Offline comparison without v10 geometry continuity')
    p.add_argument('--v10-geometry', action='store_true', help='Disable v11 pixel rescue for same-gate offline comparison')
    args = p.parse_args()
    data = json.loads(args.events.read_text(encoding='utf-8'))
    if data.get('encoding_complete') is False:
        raise RuntimeError('Incomplete video: do not assume JSON/video frame alignment')
    cap = cv2.VideoCapture(str(args.events.with_suffix('').with_suffix('.mp4')))
    detector = VisualPassDetector()
    detector.tracker = SegmentedRopeTracker()
    detector.tracker.geometry_continuity = not args.unregularized
    detector.tracker.local_refinement = not args.v10_geometry
    detector.tracker.appearance_consistency = not args.v10_geometry
    result, tiles, events, costs = [], [], [], []
    for index, original in enumerate(data['frames']):
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f'Missing video frame {index}')
        row = dict(original)
        if row['phase'] == 'round' and row['hud'] and row['ready']:
            started = time.perf_counter()
            event = detector.observe(frame, row['t'])
            costs.append(time.perf_counter()-started)
            pos = detector.position
            row.update(rope_height=round(pos.sag+pos.offset, 5),
                       rope_coverage=round(pos.coverage, 5),
                       rope_color=pos.color, rope_contrast=round(pos.contrast, 5),
                       segments=detector.tracker.segment_support,
                       replayed_candidate=event)
            row.update(detector.telemetry())
            if event:
                events.append(round(row['t'], 4))
        result.append(row)
        if index in args.frames:
            tile = cv2.resize(frame, (960, 540))
            points = detector.tracker.points
            if points is not None:
                cv2.polylines(tile, [points.astype(np.int32)], False, (0, 0, 255), 2)
            for x in (.29, .39, .49, .59, .69, .79):
                cv2.line(tile, (round(x*960), 50), (round(x*960), 370), (90, 90, 90), 1)
            cv2.rectangle(tile, (0, 0), (960, 50), (0, 0, 0), -1)
            text = (f"frame={index} t={row['t']:.3f} "
                    f"OLD h={original.get('rope_height')} c={original.get('rope_coverage')} "
                    f"NEW h={row.get('rope_height')} c={row.get('rope_coverage')}")
            cv2.putText(tile, text, (5, 21), 0, .47, (255, 255, 255), 1)
            cv2.putText(tile, str(row.get('segments', [])), (5, 43), 0, .47, (0, 255, 255), 1)
            tiles.append(tile)
    cap.release()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.update(frames=result, replayed_candidates=events)
    args.output.write_text(json.dumps(data, indent=2), encoding='utf-8')
    if tiles:
        if len(tiles) % 2:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i+2]) for i in range(0, len(tiles), 2)])
        cv2.imwrite(str(args.output.with_suffix('.jpg')), sheet)
    print(f'{args.events.name}: {len(events)} candidates, '
          f'median tracker={np.median(costs)*1000:.1f}ms, p95={np.percentile(costs,95)*1000:.1f}ms')
    print(events)


if __name__ == '__main__':
    main()
