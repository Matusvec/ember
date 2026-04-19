"""Queued TTS narration for onboarding.

ElevenLabs synthesize() + ffplay playback, serialized through one worker
thread so prompts never overlap. Fire-and-forget — callers don't await.

No-op when ELEVENLABS_API_KEY is missing so the onboarding remains usable
silently.
"""

from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import threading
import time


class Narrator:
    """Background thread that speaks queued phrases one at a time."""

    def __init__(self) -> None:
        self._q: queue.Queue[tuple[str, float] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self._speak_started_at: float = 0.0
        self.enabled: bool = bool(os.getenv("ELEVENLABS_API_KEY"))

    # ---- lifecycle ----

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="narrator")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout=2.0)

    # ---- public API ----

    def say(self, text: str, priority: bool = False) -> None:
        """Enqueue a phrase. If priority=True, clear the queue first (barge-in)."""
        if not self.enabled:
            return
        if priority:
            self._drain()
        self._q.put((text, time.monotonic()))

    def is_speaking(self) -> bool:
        return self._speaking.is_set()

    def since_start(self) -> float:
        if not self._speak_started_at:
            return 0.0
        return time.monotonic() - self._speak_started_at

    # ---- worker ----

    def _drain(self) -> None:
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def _run(self) -> None:
        try:
            from tts.service import synthesize  # type: ignore
        except Exception as exc:
            print(f"narration: TTS service unavailable ({exc})", flush=True)
            self.enabled = False
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        while not self._stop.is_set():
            item = self._q.get()
            if item is None or self._stop.is_set():
                break
            text, _enqueued_at = item
            self._speak_started_at = time.monotonic()
            self._speaking.set()
            try:
                audio = loop.run_until_complete(synthesize(text))
                self._play_blocking(audio)
            except Exception as exc:
                print(f"narration: speak failed ({exc})", flush=True)
            finally:
                self._speaking.clear()

        try:
            loop.close()
        except Exception:
            pass

    @staticmethod
    def _play_blocking(audio_bytes: bytes) -> None:
        try:
            p = subprocess.Popen(
                ["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet", "-"],
                stdin=subprocess.PIPE,
            )
        except FileNotFoundError:
            return
        try:
            if p.stdin:
                p.stdin.write(audio_bytes)
                p.stdin.close()
            p.wait(timeout=20)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
