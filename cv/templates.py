"""Match live face landmarks against recorded templates.

Loads every gestures/*.json at startup and watches the directory for changes
so new recordings appear without restarting the preview.

Per frame: normalize the live landmarks, compute L2 distance to each
template centroid, return the best match if under the configured threshold.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from recorder import normalize_face_landmarks


@dataclass
class Template:
    name: str
    vector: np.ndarray
    std: float
    source_file: Path


@dataclass
class Match:
    name: str
    distance: float


DEFAULT_THRESHOLD = 0.25  # L2 distance on normalized face space


class TemplateMatcher:
    """Loads templates from a directory, matches live frames.

    Matching is stateless per frame: just L2 to every template centroid.  For
    stability, callers can require N consecutive matches before firing.
    """

    def __init__(
        self,
        gestures_dir: Path = Path("gestures"),
        threshold: float = DEFAULT_THRESHOLD,
        consecutive_required: int = 3,
    ) -> None:
        self.dir = gestures_dir
        self.threshold = threshold
        self.consecutive_required = consecutive_required
        self.templates: list[Template] = []
        self._dir_mtime: float = 0.0
        self._file_mtimes: dict[str, float] = {}
        self._active_run: dict[str, int] = {}  # name -> consecutive match count
        self.load()

    def load(self) -> None:
        if not self.dir.exists():
            self.templates = []
            self._file_mtimes = {}
            return
        templates: list[Template] = []
        mtimes: dict[str, float] = {}
        for path in sorted(self.dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
                vec = np.array(raw["vector"], dtype=np.float32)
                templates.append(Template(
                    name=raw.get("name", path.stem),
                    vector=vec,
                    std=float(raw.get("std", 0.0)),
                    source_file=path,
                ))
                mtimes[str(path)] = path.stat().st_mtime
            except Exception as exc:
                print(f"templates: skipping {path.name} ({exc})", flush=True)
        self.templates = templates
        self._file_mtimes = mtimes
        try:
            self._dir_mtime = self.dir.stat().st_mtime
        except OSError:
            self._dir_mtime = 0.0
        print(f"templates: loaded {len(self.templates)} from {self.dir}/", flush=True)

    def maybe_reload(self) -> bool:
        """Cheap poll — reload if anything in the directory changed."""
        if not self.dir.exists():
            return False
        try:
            dir_mtime = self.dir.stat().st_mtime
        except OSError:
            return False
        changed = dir_mtime > self._dir_mtime
        if not changed:
            # Directory mtime misses edits on existing files; check each file too.
            for path, prev_mtime in list(self._file_mtimes.items()):
                try:
                    if Path(path).stat().st_mtime > prev_mtime:
                        changed = True
                        break
                except OSError:
                    changed = True
                    break
        if changed:
            self.load()
            return True
        return False

    def match(self, face_landmarks) -> Match | None:
        """Best matching template below threshold, or None.  Stateless."""
        if not self.templates:
            return None
        vec = normalize_face_landmarks(face_landmarks)
        if vec is None:
            return None
        best: Match | None = None
        for t in self.templates:
            if t.vector.shape != vec.shape:
                continue
            dist = float(np.linalg.norm(t.vector - vec))
            if dist < self.threshold and (best is None or dist < best.distance):
                best = Match(name=t.name, distance=dist)
        return best

    def active_sources(self, face_landmarks) -> dict[str, float]:
        """Per-frame boolean signal for each template.  Applies consecutive-match
        debounce so a single noisy frame does not fire."""
        out: dict[str, float] = {}
        current = self.match(face_landmarks)
        for t in self.templates:
            if current is not None and current.name == t.name:
                self._active_run[t.name] = self._active_run.get(t.name, 0) + 1
            else:
                self._active_run[t.name] = 0
            active = self._active_run[t.name] >= self.consecutive_required
            out[f"gesture:{t.name}"] = 1.0 if active else 0.0
        return out
