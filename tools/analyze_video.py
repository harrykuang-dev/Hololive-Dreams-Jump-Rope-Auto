"""Extract full-resolution gameplay frames for tuning the rope detector."""

from pathlib import Path

import cv2


VIDEO = Path(r"C:\Users\ashel\Videos\NVIDIA\Desktop\Desktop 2026.09.22 - 14.07.58.02.mp4")
OUT = Path(r"C:\Users\ashel\Downloads\Hololive-Jump-Rope-Auto\debug\video_frames")
TIMES = [44.5, 48.0, 53.4, 57.0, 62.3, 67.0, 71.2, 73.4, 80.1, 89.0, 97.9, 115.8, 124.7, 133.6, 142.5, 151.4]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(VIDEO))
    for second in TIMES:
        capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"unable to read {second}s")
        cv2.imwrite(str(OUT / f"{second:06.1f}.png"), frame)


if __name__ == "__main__":
    main()
