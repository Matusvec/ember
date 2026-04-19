"""
voice/wake.py

Wake-word detector backed by Porcupine (pvporcupine).
Listens on the microphone in a background thread and fires on_wake()
when the keyword is detected.

Built-in keywords (no training needed):
  "computer", "porcupine", "jarvis", "hey barbie", "hey google",
  "ok google", "alexa", "hey siri", "bumblebee", "terminator"

Custom "Hey Axis" wake word:
  1. Sign up free at console.picovoice.ai
  2. Train a custom keyword → download the .ppn file
  3. Set AXIS_WAKE_KEYWORD_PATH=/path/to/hey-axis.ppn in .env

pip install pvporcupine pyaudio
export PICOVOICE_ACCESS_KEY=<your free key>
"""

import os
import struct
import threading
from typing import Callable, Optional

try:
    import pvporcupine
    import pyaudio
    _PORCUPINE_AVAILABLE = True
except ImportError:
    _PORCUPINE_AVAILABLE = False

PICOVOICE_ACCESS_KEY  = os.getenv("PICOVOICE_ACCESS_KEY", "")
# Built-in keyword used when no custom .ppn is configured.
# Change to "computer" or "hey barbie" etc. for something more natural.
_BUILTIN_KEYWORD      = os.getenv("AXIS_WAKE_KEYWORD", "computer")
# Optional path to a custom .ppn model — overrides the built-in keyword.
_CUSTOM_KEYWORD_PATH  = os.getenv("AXIS_WAKE_KEYWORD_PATH", "")


class WakeWordDetector:
    """
    Background microphone listener that fires on_wake() each time the
    configured wake phrase is detected.

    When pvporcupine is not installed, falls back to blocking on ENTER so
    the rest of the voice pipeline can be developed without the dependency.
    """

    def __init__(self, on_wake: Callable[[], None]):
        self._on_wake     = on_wake
        self._thread: Optional[threading.Thread] = None
        self._stop        = threading.Event()
        self._active      = False   # suppresses re-trigger during a live session

    def start(self) -> None:
        if not _PORCUPINE_AVAILABLE:
            print("[WakeWord] pvporcupine not installed — keyboard fallback active.")
            print("[WakeWord] Press ENTER at any time to trigger voice mode.")
            target = self._keyboard_loop
        else:
            if not PICOVOICE_ACCESS_KEY:
                raise EnvironmentError(
                    "PICOVOICE_ACCESS_KEY is not set. "
                    "Get a free key at console.picovoice.ai and add it to .env"
                )
            target = self._porcupine_loop

        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()
        kw = _CUSTOM_KEYWORD_PATH or _BUILTIN_KEYWORD
        print(f"[WakeWord] Listening for: {kw}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def set_active(self, active: bool) -> None:
        """Set True while a conversation session is running to block re-trigger."""
        self._active = active

    # ── Porcupine audio loop ─────────────────────────────────────────────────

    def _porcupine_loop(self) -> None:
        kwargs: dict = {"access_key": PICOVOICE_ACCESS_KEY, "sensitivities": [0.6]}
        if _CUSTOM_KEYWORD_PATH:
            kwargs["keyword_paths"] = [_CUSTOM_KEYWORD_PATH]
        else:
            kwargs["keywords"] = [_BUILTIN_KEYWORD]

        porcupine = pvporcupine.create(**kwargs)
        pa         = pyaudio.PyAudio()
        stream     = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length,
        )
        try:
            while not self._stop.is_set():
                raw = stream.read(porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * porcupine.frame_length, raw)
                if porcupine.process(pcm) >= 0 and not self._active:
                    print("[WakeWord] Triggered.")
                    self._on_wake()
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            porcupine.delete()

    # ── Keyboard fallback ────────────────────────────────────────────────────

    def _keyboard_loop(self) -> None:
        while not self._stop.is_set():
            try:
                input()   # blocks until ENTER
                if not self._active:
                    self._on_wake()
            except EOFError:
                break