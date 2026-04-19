"""ElevenLabs speech-to-text for voice commands during onboarding.

Records a short audio clip via sounddevice, ships it to ElevenLabs STT,
and returns the transcribed text. Used on the summary screen so voice-
capable users can confirm / redo without touching head or keyboard.
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
import time
import wave
from typing import Callable

try:
    import numpy as np
    import sounddevice as sd
    _HAS_SD = True
except Exception:
    np = None  # type: ignore
    sd = None  # type: ignore
    _HAS_SD = False

_SAMPLE_RATE = 16000


def _record_to_wav(duration_s: float) -> bytes | None:
    """Record `duration_s` seconds of mono 16-bit PCM, return WAV bytes."""
    if not _HAS_SD:
        return None
    try:
        frames = int(duration_s * _SAMPLE_RATE)
        audio = sd.rec(frames, samplerate=_SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
    except Exception as exc:
        print(f"stt: recording failed ({exc})", flush=True)
        return None

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


async def _transcribe(wav_bytes: bytes) -> str:
    """Send WAV bytes to ElevenLabs and return the transcript text."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        return ""

    from elevenlabs.client import AsyncElevenLabs  # type: ignore
    client = AsyncElevenLabs(api_key=api_key)

    try:
        result = await client.speech_to_text.convert(
            file=io.BytesIO(wav_bytes),
            model_id="scribe_v1",
        )
    except Exception as exc:
        print(f"stt: transcription failed ({exc})", flush=True)
        return ""

    # The SDK returns an object with a `text` attribute in most versions;
    # fall back to stringification for older variants.
    text = getattr(result, "text", None)
    if text is None:
        text = str(result)
    return text.strip().lower()


def listen_once(duration_s: float = 3.5) -> str:
    """Record and transcribe a short clip, blocking. Returns "" on failure."""
    wav = _record_to_wav(duration_s)
    if wav is None:
        return ""
    try:
        return asyncio.run(_transcribe(wav))
    except RuntimeError:
        # Already inside a loop (unusual here) — run in a new thread.
        result: list[str] = [""]
        def _go() -> None:
            result[0] = asyncio.new_event_loop().run_until_complete(_transcribe(wav))
        t = threading.Thread(target=_go, daemon=True)
        t.start()
        t.join(timeout=15)
        return result[0]


def listen_async(duration_s: float, callback: Callable[[str], None]) -> threading.Thread:
    """Non-blocking variant — callback fires on the worker thread with the transcript."""
    def _worker() -> None:
        text = listen_once(duration_s)
        callback(text)

    t = threading.Thread(target=_worker, daemon=True, name="stt-listen")
    t.start()
    return t


# ---- Simple keyword parsers -------------------------------------------------

_YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "go", "start",
              "confirm", "correct", "right", "fine", "good", "ready", "perfect",
              "sounds good", "looks good", "let's go", "do it", "continue"}

_NO_WORDS = {"no", "nope", "redo", "again", "restart", "change", "different",
             "wrong", "back", "retry", "not quite", "cancel"}

_SKIP_WORDS = {"skip", "next", "pass", "move on", "forward"}


def parse_confirm(text: str) -> str | None:
    """Return 'yes', 'no', or None based on what the user said."""
    if not text:
        return None
    low = text.lower().strip(" .!?,")
    if any(w in low for w in _NO_WORDS):
        return "no"
    if any(w in low for w in _YES_WORDS):
        return "yes"
    return None


def parse_skip(text: str) -> bool:
    if not text:
        return False
    low = text.lower().strip(" .!?,")
    return any(w in low for w in _SKIP_WORDS)
