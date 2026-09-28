"""Extract full-resolution gameplay frames for tuning the rope detector."""

import argparse
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO = ROOT / "recordings" / "Desktop 2026.09.27 - 03.00.28.01.mp4"
OUT = ROOT / "debug" / "video_frames"
TIMES = [44.5, 48.0, 53.4, 57.0, 62.3, 67.0, 71.2, 73.4, 80.1, 89.0, 97.9, 115.8, 124.7, 133.6, 142.5, 151.4]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", nargs="?", type=Path, default=DEFAULT_VIDEO)
    args = parser.parse_args()
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise SystemExit(f"Cannot open video: {args.video}")
    OUT.mkdir(parents=True, exist_ok=True)
    for second in TIMES:
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"unable to read {second}s")
        cv2.imwrite(str(OUT / f"{second:06.1f}.png"), frame)


if __name__ == "__main__":
    main()
