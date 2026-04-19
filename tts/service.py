"""
axis/tts/service.py

ElevenLabs TTS wrapper for Axis.
Handles streaming generation, phrase caching, and priority interruption.
"""

import asyncio
import hashlib
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

from elevenlabs.client import AsyncElevenLabs

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
MODEL_ID = "eleven_turbo_v2_5"   # lowest latency model
CACHE_DIR = Path(os.getenv("AXIS_CACHE_DIR", "/tmp/axis_tts_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_client: Optional[AsyncElevenLabs] = None


def get_client() -> AsyncElevenLabs:
    global _client
    if _client is None:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ELEVENLABS_API_KEY is not set. "
                "Add it to your .env file or environment."
            )
        _client = AsyncElevenLabs(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(text: str, voice_id: str, model_id: str) -> Path:
    digest = hashlib.sha256(f"{voice_id}:{model_id}:{text}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.mp3"


async def _load_cache(path: Path) -> Optional[bytes]:
    if path.exists():
        return path.read_bytes()
    return None


async def _save_cache(path: Path, data: bytes) -> None:
    path.write_bytes(data)


# ---------------------------------------------------------------------------
# Core TTS functions
# ---------------------------------------------------------------------------

async def synthesize(text: str) -> bytes:
    """
    Returns full MP3 audio bytes for `text`.
    Checks local disk cache first — cached phrases (calibration steps,
    status messages) never hit the API twice.

    Internally collects from synthesize_stream() so there is no blocking
    isinstance / sync-generator path that could stall the event loop.
    """
    cache_path = _cache_key(text, VOICE_ID, MODEL_ID)
    cached = await _load_cache(cache_path)
    if cached:
        return cached

    chunks: list[bytes] = []
    async for chunk in synthesize_stream(text):
        chunks.append(chunk)
    data = b"".join(chunks)

    await _save_cache(cache_path, data)
    return data


async def synthesize_stream(text: str) -> AsyncGenerator[bytes, None]:
    """
    Yields MP3 chunks as they arrive — lower time-to-first-audio than
    synthesize(). Use this for long narration where you want audio to
    start playing before the full sentence is generated.
    """
    client = get_client()
    async for chunk in await client.text_to_speech.convert_as_stream(
        text=text,
        voice_id=VOICE_ID,
        model_id=MODEL_ID,
        output_format="mp3_44100_128",
    ):
        if chunk:
            yield chunk


# ---------------------------------------------------------------------------
# Pre-warm cache for all known phrases
# ---------------------------------------------------------------------------

async def prewarm(phrases: list[str]) -> None:
    """
    Call this at startup to pre-generate and cache all calibration /
    status phrases so in-session TTS has zero API latency.
    """
    tasks = [synthesize(p) for p in phrases]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for phrase, result in zip(phrases, results):
        if isinstance(result, Exception):
            print(f"[TTS prewarm] Failed for '{phrase[:40]}': {result}")