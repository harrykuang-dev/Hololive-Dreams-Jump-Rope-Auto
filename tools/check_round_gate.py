"""Read-only checks of the HUD guard against source-video game and menu frames."""
import argparse
from pathlib import Path
import sys
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision import RoundGate

parser = argparse.ArgumentParser()
parser.add_argument('video')
args = parser.parse_args()
cap = cv2.VideoCapture(args.video)
failed = []
for t, expected in [(9, False), (12, False), (17, False), (26, False), (30, False),
                    (48, True), (53.4, True), (62.3, True), (73.4, True),
                    (89, True), (115.8, True), (142.5, True), (160.3, False)]:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f'Cannot decode {t}')
    client = frame[286:944, 526:1700]
    actual = RoundGate.gameplay_visible(client)
    print(f'{t}: expected={expected} observed={actual}')
    if actual != expected:
        failed.append(t)
cap.release()
if failed:
    raise SystemExit(f'Mismatch: {failed}')
