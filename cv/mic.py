"""Rolling mic-input monitor.

Used during onboarding to detect whether the user can/does speak. Uses
sounddevice (PortAudio) if available — gracefully no-ops otherwise so the
webcam-only path keeps working on machines without audio deps.

Not a speech recognizer — just "are they making sound above room noise".
"""

from __future__ import annotations

import threading
import time

try:
    import numpy as np
    import sounddevice as sd
    _HAS_SD = True
except Exception:
    sd = None  # type: ignore
    np = None  # type: ignore
    _HAS_SD = False


class MicMonitor:
    """Background mic RMS sampler with peak-hold over a sliding window.

    Usage:
        m = MicMonitor()
        m.start()
        ...
        peak = m.peak_rms_since(t0)   # float 0..1, peak since t0
        m.stop()

    Silent machines (no mic / sounddevice missing) always report 0.0.
    """

    SAMPLE_RATE = 16000
    BLOCK_SEC = 0.05  # 50ms blocks → 20Hz update

    def __init__(self) -> None:
        self._stream = None
        self._running = False
        self._lock = threading.Lock()
        # ring of (timestamp, rms) samples — keep last ~10 seconds
        self._history: list[tuple[float, float]] = []
        self.available: bool = _HAS_SD

    def start(self) -> None:
        if not _HAS_SD or self._running:
            return
        try:
            self._stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=1,
                blocksize=int(self.SAMPLE_RATE * self.BLOCK_SEC),
                callback=self._on_block,
                dtype="float32",
            )
            self._stream.start()
            self._running = True
        except Exception as exc:
            print(f"mic: unavailable ({exc})", flush=True)
            self.available = False
            self._stream = None
            self._running = False

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._running = False

    def _on_block(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if np is None:
            return
        # RMS of this block, normalized 0..1 (clipping at 1 is fine).
        rms = float(np.sqrt(np.mean(indata.astype("float32") ** 2)))
        with self._lock:
            now = time.monotonic()
            self._history.append((now, rms))
            cutoff = now - 10.0
            # trim old samples
            i = 0
            for i, (t, _) in enumerate(self._history):
                if t >= cutoff:
                    break
            if i > 0:
                self._history = self._history[i:]

    def peak_rms_since(self, t_start: float) -> float:
        """Return max RMS recorded since t_start (monotonic seconds)."""
        with self._lock:
            return max((r for t, r in self._history if t >= t_start), default=0.0)

    def samples_since(self, t_start: float) -> list[tuple[float, float]]:
        with self._lock:
            return [(t, r) for t, r in self._history if t >= t_start]
