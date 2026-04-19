"""
axis/tts/voice_guide.py

All spoken content for Axis, organised by context.
Import PHRASES for pre-warming the cache at startup.
Call the helper functions from your calibration / mapping / driver logic.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CalibrationStep(str, Enum):
    WELCOME       = "welcome"
    SETTLE        = "settle"
    WATCHING      = "watching"
    HALFWAY       = "halfway"
    FOUND_INPUTS  = "found_inputs"
    CONFIRM       = "confirm"
    COMPLETE      = "complete"
    NO_SIGNAL     = "no_signal"


class StatusEvent(str, Enum):
    GESTURE_DETECTED   = "gesture_detected"
    GESTURE_MAPPED     = "gesture_mapped"
    CLICK_FIRED        = "click_fired"
    SCROLL_UP          = "scroll_up"
    SCROLL_DOWN        = "scroll_down"
    PROFILE_SAVED      = "profile_saved"
    PROFILE_LOADED     = "profile_loaded"
    DRIVER_STARTED     = "driver_started"
    DRIVER_STOPPED     = "driver_stopped"
    LOW_CONFIDENCE     = "low_confidence"
    CALIBRATION_NEEDED = "calibration_needed"


# ---------------------------------------------------------------------------
# Script bank
# ---------------------------------------------------------------------------

CALIBRATION_SCRIPTS: dict[CalibrationStep, str] = {
    CalibrationStep.WELCOME: (
        "Welcome to Axis. I'm going to watch you move for about ninety seconds "
        "to find the controls that work best for you. "
        "You don't need to do anything special — just relax and let me look."
    ),
    CalibrationStep.SETTLE: (
        "Get comfortable. Rest your head and body in whatever position feels natural. "
        "I'll start watching in three seconds."
    ),
    CalibrationStep.WATCHING: (
        "I'm watching now. Try a few small movements if you like — "
        "tilting your head, raising an eyebrow, opening your mouth slightly. "
        "Or just stay still. I'll find what I need either way."
    ),
    CalibrationStep.HALFWAY: (
        "Halfway there. Looking good. Keep doing whatever feels natural."
    ),
    CalibrationStep.FOUND_INPUTS: (
        "I've finished scanning. I found some reliable movements on your body. "
        "Take a look at what I detected — they're highlighted on screen. "
        "Let me know which ones feel comfortable and intentional."
    ),
    CalibrationStep.CONFIRM: (
        "Confirm the movements you want to use, then we'll map them to actions."
    ),
    CalibrationStep.COMPLETE: (
        "You're all set. Axis is now running in the background. "
        "Your body is your controller. Everything else is just your computer."
    ),
    CalibrationStep.NO_SIGNAL: (
        "I didn't detect enough reliable movement this time. "
        "That's okay — let's try again. "
        "Try to make small, deliberate movements during the scan, "
        "or adjust your position so the camera can see your face more clearly."
    ),
}


STATUS_SCRIPTS: dict[StatusEvent, str] = {
    StatusEvent.GESTURE_DETECTED:   "Gesture detected.",
    StatusEvent.GESTURE_MAPPED:     "Mapped.",
    StatusEvent.CLICK_FIRED:        "Click.",
    StatusEvent.SCROLL_UP:          "Scrolling up.",
    StatusEvent.SCROLL_DOWN:        "Scrolling down.",
    StatusEvent.PROFILE_SAVED:      "Profile saved.",
    StatusEvent.PROFILE_LOADED:     "Profile loaded. Axis is ready.",
    StatusEvent.DRIVER_STARTED:     "Axis is running.",
    StatusEvent.DRIVER_STOPPED:     "Axis paused.",
    StatusEvent.LOW_CONFIDENCE:     "Signal is weak. Try adjusting your position.",
    StatusEvent.CALIBRATION_NEEDED: "Recalibration recommended. Signal quality has dropped.",
}


# ---------------------------------------------------------------------------
# Dynamic announcement builders
# ---------------------------------------------------------------------------

@dataclass
class DetectedInput:
    label: str        # e.g. "head tilt left"
    confidence: float # 0.0–1.0


def announce_detected_inputs(inputs: list[DetectedInput]) -> str:
    """
    Builds a natural-language announcement of what Axis found.
    Example output:
      "I found 4 reliable inputs: head tilt left, head tilt right,
       eyebrow raise, and smile."
    """
    if not inputs:
        return CALIBRATION_SCRIPTS[CalibrationStep.NO_SIGNAL]

    count = len(inputs)
    labels = [i.label for i in inputs]

    if count == 1:
        items = labels[0]
    elif count == 2:
        items = f"{labels[0]} and {labels[1]}"
    else:
        items = ", ".join(labels[:-1]) + f", and {labels[-1]}"

    return (
        f"I found {count} reliable input{'s' if count != 1 else ''}: {items}. "
        "Select the ones you want to use."
    )


def announce_mapping(gesture: str, action: str) -> str:
    """
    e.g. "Head tilt left mapped to mouse left."
    """
    return f"{gesture.capitalize()} mapped to {action}."


# ---------------------------------------------------------------------------
# Master phrase list — feed to service.prewarm() at startup
# ---------------------------------------------------------------------------

PHRASES: list[str] = (
    list(CALIBRATION_SCRIPTS.values())
    + list(STATUS_SCRIPTS.values())
)