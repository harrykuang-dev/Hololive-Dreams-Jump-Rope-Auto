"""Local video and timestamped evidence for one bot-controlled game round."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


class RoundRecorder:
    def __init__(self, path: Path, first_frame: np.ndarray, fps: float = 20.0) -> None:
        if first_frame.ndim != 3 or first_frame.shape[2] != 3:
            raise ValueError("Recording requires a BGR game frame")
        self.path = Path(path)
        self.fps = fps
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.shape = first_frame.shape
        height, width = first_frame.shape[:2]
        # MP4 encoders generally require even dimensions.
        self.size = (width + width % 2, height + height % 2)
        self.writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"mp4v"),
                                      fps, self.size)
        if not self.writer.isOpened():
            self.writer.release()
            raise RuntimeError(f"無法建立錄影：{self.path}")
        self.frames: list[dict] = []

    def add(self, frame: np.ndarray, elapsed: float, *, hud: bool, ready: bool,
            candidate: bool, clicked: bool, detector_score: float,
            input_elapsed: float | None = None) -> None:
        if frame.shape != self.shape:
            raise RuntimeError("遊戲畫面尺寸在錄影中改變，已停止")
        height, width = frame.shape[:2]
        if self.size != (width, height):
            frame = cv2.copyMakeBorder(frame, 0, self.size[1] - height,
                                       0, self.size[0] - width,
                                       cv2.BORDER_CONSTANT, value=(0, 0, 0))
        self.writer.write(frame)
        self.frames.append({
            "t": round(elapsed, 4), "hud": hud, "ready": ready,
            "candidate": candidate, "clicked": clicked,
            "input_t": round(input_elapsed, 4) if input_elapsed is not None else None,
            "detector_score": round(detector_score, 4),
        })

    def close(self, *, stop_reason: str, tap_count: int,
              candidate_count: int, error: str | None) -> Path:
        self.writer.release()
        log_path = self.path.with_suffix(".events.json")
        log_path.write_text(json.dumps({
            "video": str(self.path.resolve()),
            "video_fps": self.fps,
            "stop_reason": stop_reason,
            "tap_count": tap_count,
            "candidate_count": candidate_count,
            "error": error,
            "frames": self.frames,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return log_path
