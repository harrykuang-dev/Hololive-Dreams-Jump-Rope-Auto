"""Audit completed recordings; scores must be read from result frames by a person."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import cv2


def audit_round(path: Path, score: int) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    frames = data['frames']
    if data['stop_reason'] != 'round_finished' or data['error'] is not None:
        raise ValueError(f'{path.name}: interrupted or failed round')
    if not data['encoding_complete'] or not frames:
        raise ValueError(f'{path.name}: incomplete recording')
    result_t = next((r['t'] for r in frames if r['phase'] == 'result'), None)
    if result_t is None or data['round_started_t'] is None:
        raise ValueError(f'{path.name}: missing round/result confirmation')
    after_result = sum(t >= result_t for t in data['input_times'])
    after_start = sum(a['t'] >= data['round_started_t'] for a in data['menu_actions'])
    if after_result or after_start:
        raise ValueError(f'{path.name}: input outside the permitted phase')
    video = path.with_suffix('').with_suffix('.mp4')
    cap = cv2.VideoCapture(str(video))
    try:
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not cap.isOpened() or count != len(frames) or count != data['written_video_frames']:
            raise ValueError(f'{path.name}: MP4/JSON frame mismatch')
        cap.set(cv2.CAP_PROP_POS_FRAMES, count-1)
        ok, _ = cap.read()
        if not ok:
            raise ValueError(f'{path.name}: unreadable final video frame')
    finally:
        cap.release()
    return {'recording': video.name, 'reviewed_game_score': score,
            'inputs': len(data['input_times']), 'frames': count,
            'stop_reason': data['stop_reason'], 'encoding_complete': True,
            'inputs_after_result': after_result, 'menus_after_start': after_start,
            'actual_fps': data['performance'].get('actual_round_fps')}


def audit_batch(prefix: Path, scores: list[int]) -> dict:
    if len(scores) != 7 or any(type(s) is not int or s < 0 for s in scores):
        raise ValueError('Supply seven manually reviewed nonnegative game scores')
    gui = prefix.is_dir()
    paths = sorted(prefix.glob('round-*.events.json') if gui else
                   prefix.parent.glob(prefix.name+'-round-*.events.json'))
    expected = [f'{"" if gui else prefix.name+"-"}round-{i:02d}.events.json'
                for i in range(1, 8)]
    if len(paths) != 7 or [p.name for p in paths] != expected:
        raise ValueError('Exactly seven completed round files are required')
    manifest_path = prefix/'session.json' if gui else prefix.with_suffix('.run.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['round_limit'] != 7:
        raise ValueError('Manifest is not a seven-round run')
    rounds = [audit_round(path, score) for path, score in zip(paths, scores)]
    return {'batch': prefix.name, 'executable_sha256': manifest['executable_sha256'],
            'entry_point': 'GUI' if gui else 'CLI',
            'capture_backend': manifest['capture_backend'],
            'score_source': 'Manually reviewed recorded game result frames; not input counts',
            'rounds': rounds, 'at_least_100': sum(s >= 100 for s in scores),
            'minimum': min(scores), 'median': statistics.median(scores),
            'frame_audit': 'MP4 metadata count and final-frame decode; not full-file decode'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('--scores', type=int, nargs=7, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit_batch(args.prefix, args.scores)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"7 rounds audited; >=100: {report['at_least_100']}; "
          f"minimum: {report['minimum']}; median: {report['median']}")


if __name__ == '__main__':
    main()
