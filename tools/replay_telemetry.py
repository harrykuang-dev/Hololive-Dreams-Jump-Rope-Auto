"""Replay recorded rope measurements through the current visual event gate.

This diagnoses candidate timing only. It cannot predict the game's score or
replace a fresh MP4/JSON single-round test.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rope_track import RopePosition, VisualPassDetector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    frames = json.loads(args.events.read_text(encoding="utf-8"))["frames"]
    detector = VisualPassDetector()
    predicted = []
    original = []
    for index, row in enumerate(frames):
        if row["clicked"]:
            original.append((index, row["t"]))
        if row["phase"] != "round" or not row["hud"] or not row["ready"]:
            continue
        if row["rope_height"] is None:
            continue
        position = RopePosition(row["rope_height"], row["rope_coverage"], 0,
                                row["rope_color"], row["rope_contrast"])
        detector.tracker.locate = lambda _frame, p=position: p
        candidate = detector.observe(None, row["t"])
        if candidate:
            predicted.append((index, row["t"]))
        if args.output:
            row.update(replayed_candidate=candidate, **detector.telemetry())
    if args.summary:
        predicted_indices = {index for index, _ in predicted}
        removed = [round(t, 3) for index, t in original
                   if index not in predicted_indices]
        added = [round(t, 3) for index, t in predicted
                 if not frames[index]["clicked"]]
        print(f"{args.events.name}: recorded={len(original)}, "
              f"replayed={len(predicted)}, removed={removed}, added={added}")
    else:
        print("Recorded clicks:", original)
        print("Replayed visual candidates:", predicted)
    print("Telemetry replay cannot validate game score or occluded pixels.")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'frames': frames, 'candidates': predicted}, indent=2), encoding='utf-8')


if __name__ == "__main__":
    main()
