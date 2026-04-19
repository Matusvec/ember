"""
axis/tts/router.py

FastAPI router for all TTS endpoints.
Mount this in your main app with:  app.include_router(tts_router, prefix="/tts")
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .service import synthesize, synthesize_stream, prewarm
from .voice_guide import (
    CalibrationStep,
    DetectedInput,
    StatusEvent,
    CALIBRATION_SCRIPTS,
    STATUS_SCRIPTS,
    PHRASES,
    announce_detected_inputs,
    announce_mapping,
)

tts_router = APIRouter(tags=["tts"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SpeakRequest(BaseModel):
    text: str
    stream: bool = True          # True → streaming response, False → full bytes


class CalibrationStepRequest(BaseModel):
    step: CalibrationStep


class StatusEventRequest(BaseModel):
    event: StatusEvent


class MappingAnnouncementRequest(BaseModel):
    gesture: str                 # e.g. "head tilt left"
    action: str                  # e.g. "mouse left"


class DetectedInputsRequest(BaseModel):
    inputs: list[DetectedInput]


class AACRequest(BaseModel):
    text: str                    # text the user has composed to be spoken aloud


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@tts_router.post("/speak")
async def speak(req: SpeakRequest):
    """
    Speak arbitrary text. Use stream=true (default) for lowest latency.
    The frontend plays the returned MP3 bytes directly in an <audio> element
    or via the Web Audio API.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    if req.stream:
        return StreamingResponse(
            synthesize_stream(req.text),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache"},
        )

    audio = await synthesize(req.text)
    return StreamingResponse(
        iter([audio]),
        media_type="audio/mpeg",
    )


@tts_router.post("/calibration/step")
async def speak_calibration_step(req: CalibrationStepRequest):
    """
    Speak a named calibration step. Audio is served from disk cache after
    the first call, so latency is negligible during a live session.
    """
    text = CALIBRATION_SCRIPTS[req.step]
    audio = await synthesize(text)
    return StreamingResponse(iter([audio]), media_type="audio/mpeg")


@tts_router.post("/calibration/found-inputs")
async def speak_found_inputs(req: DetectedInputsRequest):
    """
    Announce the inputs Axis detected after the calibration scan.
    Dynamic text so it is not pre-cached — still fast because it is short.
    """
    text = announce_detected_inputs(req.inputs)
    audio = await synthesize(text)
    return StreamingResponse(iter([audio]), media_type="audio/mpeg")


@tts_router.post("/status")
async def speak_status(req: StatusEventRequest):
    """
    Short status feedback: gesture detected, click fired, driver started, etc.
    All pre-cached at startup so this returns instantly.
    """
    text = STATUS_SCRIPTS[req.event]
    audio = await synthesize(text)
    return StreamingResponse(iter([audio]), media_type="audio/mpeg")


@tts_router.post("/mapping")
async def speak_mapping(req: MappingAnnouncementRequest):
    """
    Confirm a gesture→action mapping to the user.
    e.g. "Head tilt left mapped to mouse left."
    """
    text = announce_mapping(req.gesture, req.action)
    audio = await synthesize(text)
    return StreamingResponse(iter([audio]), media_type="audio/mpeg")


@tts_router.post("/aac")
async def speak_aac(req: AACRequest):
    """
    AAC output: speak text the user has composed using gesture-driven
    text selection. Streamed for minimum time-to-speech.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    return StreamingResponse(
        synthesize_stream(req.text),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# WebSocket — real-time status feed
# ---------------------------------------------------------------------------

@tts_router.websocket("/ws/status")
async def tts_status_ws(websocket: WebSocket):
    """
    WebSocket that the gesture driver connects to.
    The driver sends JSON like:
        {"event": "gesture_detected"}
        {"event": "click_fired"}
    Axis responds by pushing the pre-cached MP3 bytes back to the
    React frontend which plays them immediately.

    Protocol:
      Client → server:  {"event": "<StatusEvent value>"}
      Server → client:  binary frame = MP3 audio bytes
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            event_str = data.get("event")
            try:
                event = StatusEvent(event_str)
            except ValueError:
                await websocket.send_json({"error": f"Unknown event: {event_str}"})
                continue

            text = STATUS_SCRIPTS[event]
            audio = await synthesize(text)    # hits cache, near-zero latency
            await websocket.send_bytes(audio)

    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Startup pre-warm — call this from your app's lifespan, not on_event
# ---------------------------------------------------------------------------
# on_event("startup") is deprecated in FastAPI >= 0.93.
# In main.py, wire it like this:
#
#   from contextlib import asynccontextmanager
#   from tts.router import tts_startup
#
#   @asynccontextmanager
#   async def lifespan(app: FastAPI):
#       await tts_startup()
#       yield
#
#   app = FastAPI(lifespan=lifespan)

async def tts_startup() -> None:
    """
    Kick off background phrase pre-warming.
    Call once from your app lifespan before yielding.
    """
    asyncio.create_task(_prewarm_task())


async def _prewarm_task() -> None:
    try:
        print("[TTS] Pre-warming phrase cache...")
        await prewarm(PHRASES)
        print(f"[TTS] Cache ready — {len(PHRASES)} phrases pre-generated.")
    except Exception as e:
        print(f"[TTS] Pre-warm failed (check ELEVENLABS_API_KEY): {e}")