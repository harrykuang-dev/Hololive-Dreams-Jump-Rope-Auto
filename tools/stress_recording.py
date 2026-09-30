"""Paced seven-round lossless recording stress; no desktop or game input."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import round_recording


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    paths = [args.output/f'pressure-{i}.mp4' for i in range(1, 8)]
    if any(p.exists() or p.with_suffix('.events.json').exists() for p in paths):
        parser.error('Do not overwrite existing pressure evidence')
    real_writer = cv2.VideoWriter
    reports = []
    for index, path in enumerate(paths, 1):
        class DelayedWriter:
            def __init__(self, *parameters):
                self.writer = real_writer(*parameters)
                self.number = 0
            def isOpened(self): return self.writer.isOpened()
            def write(self, frame):
                if self.number == 0:
                    time.sleep(.85)  # More than the 32-frame RAM budget.
                if index % 2 == 0:
                    time.sleep(.020)  # Sustained throughput below 60 FPS.
                self.writer.write(frame)
                self.number += 1
            def release(self): self.writer.release()
        round_recording.cv2.VideoWriter = DelayedWriter
        frame = np.zeros((540, 960, 3), np.uint8)
        recorder = round_recording.RoundRecorder(path, frame, fps=60)
        started = time.perf_counter()
        try:
            for i in range(180):
                frame[:] = 25+(i % 30)*7
                cv2.putText(frame, str(i), (300, 270), 0, 3, (255, 255, 255), 4)
                delay = started+i/60-time.perf_counter()
                if delay > 0: time.sleep(delay)
                recorder.add(frame, time.perf_counter()-started, hud=True, ready=True,
                             candidate=False, clicked=False, detector_score=0,
                             telemetry={'phase': 'round', 'stress_index': i})
        finally:
            recorder.close(stop_reason='offline_stress', tap_count=0,
                           candidate_count=0, error=None, input_times=[])
            round_recording.cv2.VideoWriter = real_writer
        assert not recorder._worker.is_alive()
        capture = cv2.VideoCapture(str(path))
        for i in range(180):
            ok, decoded = capture.read()
            assert ok and abs(float(decoded[0:40].mean())-(25+(i % 30)*7)) < 5
        assert not capture.read()[0]
        capture.release()
        assert recorder.spilled_frames > 0
        reports.append(recorder.performance)
        print(f'round {index}: exact 180 frames, spilled={recorder.spilled_frames}, '
              f'write_max={recorder.performance["spill_write_max_ms"]:.2f} ms', flush=True)
    (args.output/'summary.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
