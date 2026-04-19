"""Ember profile — persistent per-user config at ~/.ember/profile.json.

The profile is the source of truth. It holds:
  - capabilities: what Ember detected the user can do
  - bindings: how those capabilities map to OS actions
  - settings: cursor sensitivity, filter tuning, voice on/off

Legacy mapping.json in the repo is used as a template when no profile exists.
Once onboarding completes, the profile is written and axis.py uses it every
launch. Delete ~/.ember/profile.json (or pass --onboard) to re-run setup.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

PROFILE_DIR = Path.home() / ".ember"
PROFILE_PATH = PROFILE_DIR / "profile.json"

# Capability IDs we test during onboarding.
CAPABILITY_IDS = [
    "head",       # nose-tip tracking (head pose)
    "mouth",      # mouth open
    "blink",      # eye closure
    "brow",       # eyebrow raise
    "hand",       # index fingertip
    "voice",      # mic input detected
    "keyboard",   # any key pressed during test
]


# ---- Interaction-mode inference -------------------------------------------
#
# The mode describes how the user PREFERS to interact, not just what they
# physically can do. Voice-first users (likely blind or severely motor
# impaired) need screen narration + voice command execution. Visual-only
# users (likely deaf) should never rely on TTS. "Full" means everything.

INTERACTION_MODES = ("full", "voice_first", "visual_only", "motor_limited")


def infer_mode(caps: dict[str, bool]) -> str:
    """Derive primary interaction mode from detected capabilities.

    Heuristics (intentionally simple, erring toward the more accessible mode):
      - voice=yes, no face/hand signals → voice_first (likely blind or motor)
      - voice=no, any visible input signal → visual_only (likely deaf)
      - voice=yes AND any visual input → full
      - otherwise (weak signals all around) → motor_limited
    """
    has_voice = bool(caps.get("voice"))
    has_visual = any(caps.get(k) for k in ("head", "mouth", "blink", "brow", "hand"))
    has_keyboard = bool(caps.get("keyboard"))

    if has_voice and not has_visual:
        return "voice_first"
    if not has_voice and has_visual:
        return "visual_only"
    if has_voice and has_visual:
        return "full"
    if has_keyboard:
        return "motor_limited"
    return "motor_limited"


def mode_preferences(mode: str) -> dict[str, Any]:
    """Preferences derived from a mode.

    These drive runtime behavior:
      - narration_enabled: agent describes screen changes aloud
      - tts_enabled:       use speech output (off for deaf users)
      - voice_control:     agent accepts commands like "open firefox"
      - auto_wake:         ElevenLabs session auto-starts on launch
    """
    if mode == "voice_first":
        return {
            "narration_enabled": True,
            "tts_enabled": True,
            "voice_control": True,
            "auto_wake": True,
        }
    if mode == "visual_only":
        return {
            "narration_enabled": False,
            "tts_enabled": False,
            "voice_control": False,
            "auto_wake": False,
        }
    if mode == "full":
        # Always-on voice help by default -- user may need to ask Ember a
        # question at any moment while working. Set auto_wake:false in
        # profile.json to require a wake gesture/key instead.
        return {
            "narration_enabled": False,
            "tts_enabled": True,
            "voice_control": True,
            "auto_wake": True,
        }
    # motor_limited
    return {
        "narration_enabled": False,
        "tts_enabled": True,
        "voice_control": True,
        "auto_wake": True,
    }


def default_abilities() -> dict[str, Any]:
    """User-self-reported abilities. Inferred from capabilities initially,
    overridden by the agent asking directly during setup.

    can_see / can_hear / can_speak / can_type each: True, False, or None
    (meaning unknown / not asked). The agent fills these in during setup
    so the runtime behavior can adapt (e.g. narrate screen for can_see=False).
    `confirmed` flips true once the agent has asked at least the vision and
    hearing questions -- before that the values are just guesses.
    """
    return {
        "can_see": None,
        "can_hear": None,
        "can_speak": None,
        "can_use_hands": None,
        "can_type": None,
        "confirmed": False,
    }


def abilities_from_capabilities(caps: dict[str, bool]) -> dict[str, Any]:
    """Best-guess abilities from raw capability detection."""
    return {
        "can_see": True,  # default assumption -- agent asks to confirm
        "can_hear": True,
        "can_speak": bool(caps.get("voice")),
        "can_use_hands": bool(caps.get("hand")),
        "can_type": bool(caps.get("keyboard")),
        "confirmed": False,
    }


def apply_ability_preferences(prefs: dict[str, Any],
                              abilities: dict[str, Any]) -> dict[str, Any]:
    """Refine mode preferences using explicit self-reported abilities.

    Runtime flags this sets:
      tts_enabled         -- False when can_hear=False (deaf users get captions)
      narration_enabled   -- True when can_see=False (aggressive description)
      voice_control       -- False when can_speak=False (no ConvAI input)
      auto_wake           -- True for blind / voice-primary users
      show_captions       -- True when can_hear=False (visual agent output)
      keyboard_always_on  -- True when user can't speak AND can't physically
                             type -- they'll dwell-type with head cursor.
    """
    out = dict(prefs)
    see   = abilities.get("can_see")
    hear  = abilities.get("can_hear")
    speak = abilities.get("can_speak")
    hands = abilities.get("can_use_hands")
    typ   = abilities.get("can_type")

    if hear is False:
        out["tts_enabled"] = False
        out["narration_enabled"] = False
        out["show_captions"] = True
    else:
        out.setdefault("show_captions", False)

    if see is False:
        out["narration_enabled"] = True
        out["voice_control"] = True
        out["auto_wake"] = True

    if speak is False:
        out["voice_control"] = False
        out["auto_wake"] = False
    elif speak is True:
        out.setdefault("voice_control", True)

    # Dwell-typing on the on-screen keyboard is their keyboard when they can
    # neither speak nor use a hardware keyboard. Needs cursor control, so we
    # check that there's at least a head/hand capability upstream; otherwise
    # the keyboard is useless. (Caller ensures that — this helper only sets
    # the pref.)
    if speak is False and typ is False:
        out["keyboard_always_on"] = True
    else:
        out.setdefault("keyboard_always_on", False)

    return out


def default_profile() -> dict[str, Any]:
    return {
        "version": 3,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "capabilities": {cid: False for cid in CAPABILITY_IDS},
        "bindings": [],
        "cursor_sensitivity": 4000,
        "filter": {"min_cutoff": 1.0, "beta": 0.05},
        "voice_enabled": False,
        "interaction_mode": "full",
        "preferences": mode_preferences("full"),
        "user_abilities": default_abilities(),
    }


def load() -> dict[str, Any] | None:
    """Return the profile dict, or None if it doesn't exist / is invalid."""
    if not PROFILE_PATH.exists():
        return None
    try:
        return json.loads(PROFILE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def exists() -> bool:
    return PROFILE_PATH.exists()


def save(profile: dict[str, Any]) -> Path:
    """Write the profile atomically. Creates ~/.ember if missing."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROFILE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2))
    tmp.replace(PROFILE_PATH)
    return PROFILE_PATH


def bindings_from_capabilities(caps: dict[str, bool]) -> list[dict[str, Any]]:
    """Auto-generate sensible bindings from detected capabilities.

    Rules:
      - head capable → head drives cursor
      - hand capable AND head not → finger drives cursor (fallback)
      - mouth capable → left_press (hold to drag)
      - blink capable AND mouth not → blink click
      - brow capable AND mouth not AND blink not → brow click

    Only one cursor source and one primary click are enabled by default — the
    user can flip others on in the profile file or a future config UI.
    """
    bindings: list[dict[str, Any]] = []

    if caps.get("head"):
        bindings.append({
            "id": "head_cursor",
            "source": "nose",
            "action": "cursor_xy",
            "enabled": True,
            "invert_x": False,
            "invert_y": False,
        })
    if caps.get("hand"):
        bindings.append({
            "id": "finger_cursor",
            "source": "index_tip",
            "action": "cursor_xy",
            "enabled": not caps.get("head", False),
            "invert_x": False,
            "invert_y": False,
        })

    primary_click_chosen = False
    if caps.get("mouth"):
        bindings.append({
            "id": "mouth_click",
            "source": "mouth",
            "action": "left_press",
            "enabled": True,
            "threshold": 0.08,
        })
        primary_click_chosen = True
    if caps.get("blink"):
        bindings.append({
            "id": "blink_click",
            "source": "blink",
            "action": "left_click",
            "enabled": not primary_click_chosen,
            "ear_threshold": 0.18,
            "min_closed_ms": 200,
        })
        if not primary_click_chosen:
            primary_click_chosen = True
    if caps.get("brow"):
        bindings.append({
            "id": "brow_click",
            "source": "brow",
            "action": "left_click",
            "enabled": not primary_click_chosen,
            "threshold": 0.06,
        })

    return bindings


def from_capabilities(caps: dict[str, bool]) -> dict[str, Any]:
    """Build a fresh profile dict from a capability map."""
    prof = default_profile()
    prof["capabilities"] = {cid: bool(caps.get(cid, False)) for cid in CAPABILITY_IDS}
    prof["bindings"] = bindings_from_capabilities(prof["capabilities"])
    prof["voice_enabled"] = bool(caps.get("voice", False))
    prof["user_abilities"] = abilities_from_capabilities(prof["capabilities"])
    mode = infer_mode(prof["capabilities"])
    prof["interaction_mode"] = mode
    prefs = mode_preferences(mode)
    # Key refinement: if the user has voice but cannot type by hand (no
    # keyboard detected), voice IS their keyboard. Auto-start the voice
    # session so they never have to press a key to activate it. Someone
    # who can only tilt their head + open their mouth needs this.
    can_type_by_hand = bool(caps.get("keyboard"))
    if caps.get("voice") and not can_type_by_hand:
        prefs["auto_wake"] = True
        prefs["voice_control"] = True
    # Layer self-reported abilities on top of mode-based prefs so deaf/blind/
    # mute flags actually change runtime behavior.
    prefs = apply_ability_preferences(prefs, prof["user_abilities"])
    prof["preferences"] = prefs
    if prof["preferences"].get("voice_control"):
        prof["voice_enabled"] = True
    return prof
