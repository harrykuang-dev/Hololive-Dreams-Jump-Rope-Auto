"""Measure candidate rope pixels in the supplied gameplay recording."""

import argparse
from pathlib import Path

import cv2
import numpy as np


FRAMES = Path(__file__).resolve().parents[1] / "debug" / "video_frames"


def rope_mask(frame: np.ndarray) -> np.ndarray:
    """Return bright, low-saturation blue/white pixels typical of the rope."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, (85, 35, 80), (125, 255, 255))
    white = cv2.inRange(hsv, (0, 0, 160), (180, 75, 255))
    return cv2.bitwise_or(blue, white)


def danger_score(frame: np.ndarray, crop: tuple[int, int, int, int]) -> int:
    # Coordinates are normalized to the visible game client in the recording.
    left, top, right, bottom = crop
    game = frame[top:bottom, left:right]
    gh, gw = game.shape[:2]
    region = game[int(gh * 0.52):int(gh * 0.82), int(gw * 0.34):int(gw * 0.76)]
    mask = rope_mask(region)
    # Thin horizontal/diagonal rope segments survive this opening better than
    # scattered highlights from characters and scenery.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1))
    joined = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return int(np.count_nonzero(joined))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video")
    parser.add_argument("--start", type=float, default=44.0)
    parser.add_argument("--end", type=float, default=76.0)
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--crop", nargs=4, type=int, default=(448, 144, 1773, 889),
                        metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    args = parser.parse_args()
    crop = tuple(args.crop)
    if args.video:
        capture = cv2.VideoCapture(args.video)
        timestamp = args.start
        while timestamp <= args.end:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            print(f"{timestamp:.3f} {danger_score(frame, crop)}")
            timestamp += args.step
        return
    for path in sorted(FRAMES.glob("*.png")):
        frame = cv2.imread(str(path))
        print(path.stem, danger_score(frame, crop))


if __name__ == "__main__":
    main()
