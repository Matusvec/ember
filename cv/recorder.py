"""Record a face pose as a template.

Collects landmark frames over a short window, normalizes each frame so the
template is invariant to head position/scale/distance from camera, averages
them into a centroid, and writes to gestures/<name>.json.

Normalization: center on the nose tip (landmark 1), then divide by face
height (distance between landmark 10 — forehead, and 152 — chin). Result is
a fixed-length float vector you can L2-compare across recordings.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

NOSE = 1
FOREHEAD = 10
CHIN = 152


def normalize_face_landmarks(face_landmarks) -> np.ndarray | None:
    """Return a flat (468*3,) np.array of normalized face landmarks, or None."""
    if face_landmarks is None:
        return None
    lms = face_landmarks[0].landmark
    pts = np.array([(lm.x, lm.y, lm.z) for lm in lms], dtype=np.float32)
    center = pts[NOSE].copy()
    pts -= center
    height = np.linalg.norm(pts[FOREHEAD] - pts[CHIN])
    if height < 1e-6:
        return None
    pts /= height
    return pts.flatten()


@dataclass
class GestureRecording:
    started_at: float
    hold_seconds: float
    frames: list[np.ndarray] = field(default_factory=list)

    def add(self, vec: np.ndarray) -> None:
        self.frames.append(vec)

    def elapsed(self, now: float) -> float:
        return now - self.started_at

    def is_done(self, now: float) -> bool:
        return self.elapsed(now) >= self.hold_seconds

    def save(self, name: str, out_dir: Path) -> Path:
        if not self.frames:
            raise RuntimeError("no frames captured — face not visible during recording")
        stack = np.stack(self.frames)
        centroid = stack.mean(axis=0)
        std = float(np.linalg.norm(stack.std(axis=0)))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.json"
        payload = {
            "name": name,
            "source": "face",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "n_samples": len(self.frames),
            "std": std,
            "vector": centroid.tolist(),
        }
        path.write_text(json.dumps(payload))
        return path


class GestureRecorder:
    """State machine around a single recording session.

    Usage:
        rec = GestureRecorder(out_dir=Path("gestures"))
        rec.start(name="left_cheek_squint", countdown_s=3.0, hold_s=1.0)
        # each frame:
        if rec.active:
            rec.feed(face_landmarks, now)
            if rec.just_finished:
                path = rec.commit()
    """

    def __init__(self, out_dir: Path = Path("gestures")) -> None:
        self.out_dir = out_dir
        self.name: str | None = None
        self.countdown_s: float = 3.0
        self.hold_s: float = 1.0
        self.started_at: float = 0.0
        self.recording: GestureRecording | None = None
        self.just_finished: bool = False
        self.last_saved_path: Path | None = None

    @property
    def active(self) -> bool:
        return self.name is not None and not self.just_finished

    def start(self, name: str, *, countdown_s: float = 3.0, hold_s: float = 1.0) -> None:
        if self.active:
            return
        self.name = name
        self.countdown_s = countdown_s
        self.hold_s = hold_s
        self.started_at = time.monotonic()
        self.recording = None
        self.just_finished = False

    def cancel(self) -> None:
        self.name = None
        self.recording = None
        self.just_finished = False

    def phase(self, now: float) -> str:
        """Returns 'countdown', 'recording', 'done', or 'idle'."""
        if self.name is None:
            return "idle"
        if self.just_finished:
            return "done"
        elapsed = now - self.started_at
        if elapsed < self.countdown_s:
            return "countdown"
        return "recording"

    def countdown_remaining(self, now: float) -> float:
        return max(0.0, self.countdown_s - (now - self.started_at))

    def record_progress(self, now: float) -> float:
        if self.recording is None:
            return 0.0
        return min(1.0, self.recording.elapsed(now) / self.recording.hold_seconds)

    def feed(self, face_landmarks, now: float) -> None:
        if not self.active:
            return
        phase = self.phase(now)
        if phase == "countdown":
            return
        if phase == "recording":
            if self.recording is None:
                self.recording = GestureRecording(started_at=now, hold_seconds=self.hold_s)
            vec = normalize_face_landmarks(face_landmarks)
            if vec is not None:
                self.recording.add(vec)
            if self.recording.is_done(now):
                self._finalize()

    def _finalize(self) -> None:
        if self.recording is None or self.name is None:
            return
        try:
            self.last_saved_path = self.recording.save(self.name, self.out_dir)
        except RuntimeError as exc:
            print(f"recorder: {exc}", flush=True)
            self.last_saved_path = None
        self.just_finished = True

    def commit(self) -> Path | None:
        """Clear the finished recording and return where it was written (or None)."""
        path = self.last_saved_path
        self.name = None
        self.recording = None
        self.just_finished = False
        self.last_saved_path = None
        return path
