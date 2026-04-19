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


def default_profile() -> dict[str, Any]:
    return {
        "version": 2,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "capabilities": {cid: False for cid in CAPABILITY_IDS},
        "bindings": [],
        "cursor_sensitivity": 4000,
        "filter": {"min_cutoff": 1.0, "beta": 0.05},
        "voice_enabled": False,
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
    return prof
