"""Make a timestamped contact sheet from a local gameplay recording."""

import argparse
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, default=Path("debug/contact-sheet.jpg"))
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--frame-at", type=float)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise SystemExit(f"Cannot open video: {args.video}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    if fps <= 0 or frame_count <= 0:
        raise SystemExit("Cannot read video duration")
    duration = frame_count / fps
    end = min(duration - 0.2, args.end if args.end is not None else duration - 0.2)
    if not 0 <= args.start <= end:
        raise SystemExit("Invalid time range")
    if args.frame_at is not None:
        capture.set(cv2.CAP_PROP_POS_MSEC, args.frame_at * 1000)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Cannot decode frame at {args.frame_at:.2f}s")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.output), frame):
            raise RuntimeError(f"Cannot write {args.output}")
        capture.release()
        print(args.output.resolve())
        return
    tiles = []
    for second in np.linspace(args.start, end, args.samples):
        capture.set(cv2.CAP_PROP_POS_MSEC, float(second * 1000))
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Cannot decode frame at {second:.2f}s")
        tile = cv2.resize(frame, (480, 270))
        cv2.rectangle(tile, (0, 0), (130, 26), (0, 0, 0), -1)
        cv2.putText(tile, f"{second:.1f}s", (8, 19), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 2)
        tiles.append(tile)
    capture.release()
    rows = []
    for index in range(0, len(tiles), args.columns):
        row = tiles[index:index + args.columns]
        row += [np.zeros_like(tiles[0])] * (args.columns - len(row))
        rows.append(np.hstack(row))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), np.vstack(rows)):
        raise RuntimeError(f"Cannot write {args.output}")
    print(f"{duration:.2f}s, {fps:.3f} fps: {args.output.resolve()}")


if __name__ == "__main__":
    main()
