"""
voice/bridge.py

VoiceBridge — the main orchestrator for the voice pipeline.

Lifecycle:
  1. WakeWordDetector runs on a background thread, always listening
  2. Wake word fires → AxisConversation starts (ElevenLabs ConvAI session)
  3. Conversation ends → WakeWordDetector resumes
  4. ScreenNarrator runs as a background asyncio task if AXIS_CONTINUOUS_NARRATION=1

The bridge runs in its own asyncio loop, entirely separate from the CV
pipeline's 30 fps capture loop. Both pipelines share one ActionDispatcher
and nothing else.

Wire into your main entry point:
    from tools.actions import ActionDispatcher
    from voice.bridge import VoiceBridge

    dispatcher = ActionDispatcher(virtual_input=matus_virtual_mouse)

    # Launch voice pipeline in its own thread and event loop
    import asyncio, threading
    voice_loop = asyncio.new_event_loop()
    bridge = VoiceBridge(dispatcher)
    threading.Thread(
        target=voice_loop.run_until_complete,
        args=(bridge.run(),),
        daemon=True,
    ).start()

    # CV pipeline continues on the main thread as before.
"""

import asyncio
import os
import threading
from typing import Optional

from tools.actions import ActionDispatcher
from tts.service import synthesize
from voice.conversation import AxisConversation
from voice.narrate import ScreenNarrator
from voice.wake import WakeWordDetector

_CONTINUOUS_NARRATION = os.getenv("AXIS_CONTINUOUS_NARRATION", "0") == "1"


class VoiceBridge:
    def __init__(self, dispatcher: ActionDispatcher):
        self._dispatcher = dispatcher
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session: Optional[AxisConversation] = None

        # Narrator: wired into the dispatcher so narrate_screen tool works
        self._narrator = ScreenNarrator(speak_fn=self._speak_sync)
        self._dispatcher._narrate = self._narrator.get_screen_context

        # Wake word: fires _on_wake from a background thread
        self._wake = WakeWordDetector(on_wake=self._on_wake)

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Start the voice pipeline. Designed to be the sole coroutine on a
        dedicated asyncio event loop (see module docstring).
        Never call this on the same loop as the CV pipeline.
        """
        self._loop = asyncio.get_running_loop()
        self._wake.start()
        print("[Voice] Ready — waiting for wake word.")

        tasks: list[asyncio.Task] = []
        if _CONTINUOUS_NARRATION:
            tasks.append(asyncio.create_task(self._narrator.start_continuous()))
            print("[Voice] Continuous screen narration enabled.")

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self._wake.stop()
            self._narrator.stop()
            for t in tasks:
                t.cancel()
            if self._session:
                self._session.end()

    def stop(self) -> None:
        """Shut down the voice pipeline from another thread."""
        self._wake.stop()
        self._narrator.stop()
        if self._session:
            self._session.end()

    # ── Wake word → conversation ──────────────────────────────────────────────

    def _on_wake(self) -> None:
        """
        Called by WakeWordDetector from its background thread.
        Schedules session start on the bridge's own event loop so all
        async operations happen in one place.
        """
        if self._session is not None:
            return
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._start_session)

    def _start_session(self) -> None:
        print("[Voice] Starting conversation session...")
        self._wake.set_active(True)
        self._session = AxisConversation(
            dispatcher=self._dispatcher,
            on_end=self._on_session_end,
            on_transcript=lambda t: print(f"[Transcript] {t}"),
        )
        self._session.start()

    def _on_session_end(self) -> None:
        print("[Voice] Session ended. Returning to wake word.")
        self._session = None
        self._wake.set_active(False)

    # ── Audio output helper for narrator ─────────────────────────────────────

    def _speak_sync(self, text: str) -> None:
        """
        Called synchronously by ScreenNarrator. Schedules async audio
        generation on the bridge's event loop.
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._speak_async(text), self._loop)

    async def _speak_async(self, text: str) -> None:
        """Generate audio via the existing TTS service and play it locally."""
        try:
            audio = await synthesize(text)
            await _play_audio(audio)
        except Exception as exc:
            print(f"[Voice] TTS error: {exc}")


# ── Audio playback (Linux — mpv with sounddevice fallback) ───────────────────

async def _play_audio(mp3_bytes: bytes) -> None:
    """
    Play MP3 bytes through local speakers.
    Primary: sounddevice + pydub (pip install sounddevice pydub)
    Fallback: write to /tmp and play with mpv/aplay
    """
    try:
        import io
        import numpy as np
        import sounddevice as sd
        from pydub import AudioSegment

        seg     = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
        samples /= 2 ** (seg.sample_width * 8 - 1)
        sd.play(samples, samplerate=seg.frame_rate, blocking=False)
    except Exception:
        import tempfile, subprocess
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            tmp = f.name
        subprocess.Popen(
            ["mpv", "--no-terminal", "--really-quiet", tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )