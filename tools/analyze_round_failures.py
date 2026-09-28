"""Locate life losses in a recorded game and align them with actual input times.

This is read-only with respect to the game. Video frame N corresponds to JSON
frames[N]; fixed MP4 playback seconds are not the real capture clock.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def lives_in(frame):
    small = cv2.resize(frame, (960, 540))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv[200:222], (35, 100, 130), (85, 255, 255))
    return sum(np.count_nonzero(green[:, x:x+22]) >= 60 for x in (71, 96, 120))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.events.read_text(encoding="utf-8"))
    if data.get('encoding_complete') is False:
        raise RuntimeError('Incomplete video: cannot align failure frames')
    rows = data["frames"]
    video = args.events.with_suffix("").with_suffix(".mp4")
    out = args.output or args.events.parent / (video.stem + "-failures")
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    assert cap.isOpened(), video
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == len(rows), "MP4/JSON mismatch"
    known, pending, pending_start, failures = 3, 0, 0, []
    for i, row in enumerate(rows):
        ok, frame = cap.read()
        assert ok, i
        lives = lives_in(frame)
        row["lives_observed"] = int(lives)
        if row["t"] < data["round_started_t"] or known == 0:
            continue
        if lives < known:
            if pending == 0:
                pending_start = i
            pending += 1
            if pending >= 3:
                failures.append({"frame": pending_start,
                                 "t": rows[pending_start]["t"],
                                 "from_lives": known, "to_lives": int(lives)})
                known, pending = int(lives), 0
        else:
            pending = 0
    times = np.array([row["t"] for row in rows])
    for number, failure in enumerate(failures, 1):
        t = failure["t"]
        window = [dict(frame=i, **row) for i, row in enumerate(rows)
                  if t-1.6 <= row["t"] <= t+.2]
        failure["window"] = window
        failure["recent_inputs"] = [v for v in data["input_times"] if t-2 <= v <= t+.2]
        tiles = []
        for at in np.linspace(t-1.3, t+.15, 12):
            index = min(len(rows)-1, int(np.searchsorted(times, at)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
            assert ok
            row = rows[index]
            tile = cv2.resize(frame, (640, 360))
            cv2.rectangle(tile, (0, 0), (640, 48), (0, 0, 0), -1)
            line1 = f"t={row['t']:.3f} frame={index} lives={row['lives_observed']} ready={row['ready']} CLICK={row['clicked']}"
            line2 = f"h={row.get('rope_height')} cov={row.get('rope_coverage')} color={row.get('rope_color')}"
            cv2.putText(tile, line1, (5, 18), 0, .48, (0, 255, 255), 1)
            cv2.putText(tile, line2, (5, 39), 0, .48, (255, 255, 255), 1)
            tiles.append(tile)
        sheet = np.vstack([np.hstack(tiles[i:i+3]) for i in range(0, 12, 3)])
        path = out / f"loss-{number}.jpg"
        assert cv2.imwrite(str(path), sheet)
        print(f"{video.stem} loss {number}: frame={failure['frame']} t={t:.3f}, "
              f"inputs={failure['recent_inputs']}, sheet={path}")
    cap.release()
    (out / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
