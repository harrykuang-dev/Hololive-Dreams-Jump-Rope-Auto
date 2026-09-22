"""Replay the provided recording through RopeDetector without clicking a game."""

from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vision import RopeDetector


VIDEO = Path(r"C:\Users\ashel\Videos\NVIDIA\Desktop\Desktop 2026.09.22 - 14.07.58.02.mp4")
# Exact visible game client bounds in the 1920x1080 recording.
GAME_BOUNDS = (526, 286, 1700, 944)  # left, top, right, bottom


def main() -> None:
    capture = cv2.VideoCapture(str(VIDEO))
    fps = capture.get(cv2.CAP_PROP_FPS)
    detector = RopeDetector()
    events: list[tuple[float, float]] = []
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        second = index / fps
        index += 1
        if not 42.0 <= second <= 156.0 or index % 3:
            continue
        left, top, right, bottom = GAME_BOUNDS
        game = frame[top:bottom, left:right]
        if detector.observe(game, second):
            events.append((second, detector.last_score))
    print(f"events={len(events)}")
    print(" ".join(f"{event:.2f}:{score:.0f}" for event, score in events))


if __name__ == "__main__":
    main()
