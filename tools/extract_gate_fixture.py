"""Preserve compact measured sequences for decision regression, not game scores."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--native-samples', action='store_true',
                        help='Read replay_visual_pass samples at their native timestamps')
    args = parser.parse_args()
    data = json.loads(args.events.read_text(encoding='utf-8'))
    if args.native_samples:
        rows = [r[:5] for r in data['samples']]
    else:
        rows = [[r['t'], r['rope_height'], r['rope_coverage'], r['rope_color'],
                 r['rope_contrast']] for r in data['frames']
                if r['phase'] == 'round' and r['hud'] and r['ready']
                and r.get('rope_height') is not None]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        'source': args.events.name,
        'columns': ['t', 'height', 'coverage', 'color', 'contrast'],
        'measurements': rows,
    }, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    main()
