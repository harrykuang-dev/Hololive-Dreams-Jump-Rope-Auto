"""Read-only scan of startup page recognition in a saved client MP4."""

import argparse
from collections import Counter
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import StartupScreen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise SystemExit(f"Cannot open: {args.video}")
    screen = StartupScreen()
    counts = Counter()
    detections = []
    indices = {name: [] for name in StartupScreen.BUTTONS}
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        name = screen.identify(frame)
        counts[name or "unknown"] += 1
        if name and (not detections or detections[-1][1] != name):
            detections.append((index, name))
        if name:
            indices[name].append(index)
        index += 1
    capture.release()
    print("frames:", index, "counts:", dict(counts))
    print("first detections by transition:", detections[:30])
    print("detected frame indices:", {key: value[:30] for key, value in indices.items()})


if __name__ == "__main__":
    main()
