"""Extract a short lossless pixel sequence for tracking regression (no inputs)."""
import argparse
import json
from pathlib import Path
import cv2


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('events', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--first', type=int, required=True)
    p.add_argument('--last', type=int, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise SystemExit('Refusing to overwrite fixture directory')
    data = json.loads(a.events.read_text(encoding='utf8'))
    cap = cv2.VideoCapture(str(a.events.with_suffix('').with_suffix('.mp4')))
    assert data.get('encoding_complete', True)
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == len(data['frames'])
    assert 0 <= a.first <= a.last < len(data['frames'])
    a.output.mkdir(parents=True)
    cap.set(cv2.CAP_PROP_POS_FRAMES, a.first)
    rows = []
    for i in range(a.first, a.last+1):
        ok, frame = cap.read()
        assert ok
        name = f'{i}.png'
        assert cv2.imwrite(str(a.output/name), cv2.resize(frame, (960, 540)))
        rows.append({'frame': i, 't': data['frames'][i]['t'], 'file': name})
    cap.release()
    (a.output/'sequence.json').write_text(json.dumps({'source': a.events.name, 'frames': rows}, indent=2))


if __name__ == '__main__':
    main()
