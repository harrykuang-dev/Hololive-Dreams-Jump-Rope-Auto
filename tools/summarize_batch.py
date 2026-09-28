"""Create a result-frame sheet and audit JSON inputs; never infer score from taps."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prefix = Path(args.prefix)
    tiles = []
    for path in sorted(prefix.parent.glob(prefix.name+'*.events.json')):
        data = json.loads(path.read_text(encoding='utf8'))
        assert data.get('encoding_complete', True)
        cap = cv2.VideoCapture(str(path.with_suffix('').with_suffix('.mp4')))
        assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == len(data['frames'])
        cap.set(cv2.CAP_PROP_POS_FRAMES, len(data['frames'])-8)
        ok, frame = cap.read()
        cap.release()
        assert ok
        tile = cv2.resize(frame, (640, 360))
        cv2.putText(tile, path.stem[-15:], (10, 24), 0, .6, (0, 0, 0), 2)
        tiles.append(tile)
        result = next((r['t'] for r in data['frames'] if r['phase'] == 'result'), None)
        print(path.name, 'inputs=', len(data['input_times']), 'after_result=',
              sum(t >= result for t in data['input_times']) if result is not None else 'no_result', 'menus_after_start=',
              sum(a['t'] >= data['round_started_t'] for a in data['menu_actions']),
              'stop=', data['stop_reason'], 'error=', data['error'])
    if len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(args.output), np.vstack([np.hstack(tiles[i:i+2]) for i in range(0, len(tiles), 2)]))


if __name__ == '__main__':
    main()
