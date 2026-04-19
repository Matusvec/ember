"""Ember — unified entry point.

Runs the CV pipeline (head/gesture → virtual cursor) and, optionally, the
ElevenLabs voice pipeline (wake word → conversation → action dispatcher).

On first launch (no ~/.ember/profile.json), runs the guided onboarding
wizard that discovers the user's capabilities and writes a profile. On every
subsequent launch, the profile is loaded and the pipelines start directly.

Usage:
    python axis.py                     # auto: onboard if no profile, then run
    python axis.py --onboard           # force re-run onboarding
    python axis.py --no-onboard        # skip onboarding even on first launch
    python axis.py --voice             # enable voice pipeline (overrides profile)
    python axis.py --no-voice          # disable voice pipeline
    python axis.py --install-autostart # write ~/.config/autostart/ember.desktop
    python axis.py --uninstall-autostart

Environment (loaded from .env via python-dotenv):
    ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID  for voice
    PICOVOICE_ACCESS_KEY                     for wake word (fallback: press ENTER)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent
CV_DIR = ROOT / "cv"

# cv/ modules do `from cursor import ...` — add cv/ to path so we can import them.
sys.path.insert(0, str(CV_DIR))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Ember — adaptive accessibility input layer")
    voice = ap.add_mutually_exclusive_group()
    voice.add_argument("--voice", action="store_true", help="enable ElevenLabs voice pipeline")
    voice.add_argument("--no-voice", action="store_true", help="force-disable voice pipeline")
    onboard = ap.add_mutually_exclusive_group()
    onboard.add_argument("--onboard", action="store_true", help="force re-run onboarding")
    onboard.add_argument("--no-onboard", action="store_true", help="skip onboarding")
    ap.add_argument("--install-autostart", action="store_true",
                    help="install ~/.config/autostart/ember.desktop and exit")
    ap.add_argument("--uninstall-autostart", action="store_true",
                    help="remove autostart entry and exit")
    ap.add_argument("--os", choices=["linux", "windows", "auto"], default="auto",
                    help="Target OS for CV backend (default: auto-detect)")
    ap.add_argument("--mapping", default=None,
                    help="override mapping path (default: ~/.ember/profile.json)")
    ap.add_argument("--gestures", default=str(ROOT / "gestures"),
                    help="Directory for recorded gesture templates")
    preview = ap.add_mutually_exclusive_group()
    preview.add_argument("--no-preview", action="store_true",
                         help="Run CV runtime without any preview window (headless).")
    preview.add_argument("--pip", action="store_true",
                         help="Show a small picture-in-picture preview in the corner.")
    return ap.parse_args()


def voice_wanted(args: argparse.Namespace, profile: dict | None) -> bool:
    if args.no_voice:
        return False
    if args.voice:
        return True
    if profile and profile.get("voice_enabled"):
        return True
    return os.getenv("AXIS_ENABLE_VOICE", "0") == "1"


def should_onboard(args: argparse.Namespace, profile: dict | None) -> bool:
    if args.no_onboard:
        return False
    if args.onboard:
        return True
    return profile is None


def start_voice_pipeline(virtual_mouse) -> threading.Thread | None:
    missing = [k for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID") if not os.getenv(k)]
    if missing:
        print(f"voice: disabled — missing env vars: {', '.join(missing)}", flush=True)
        return None

    try:
        import asyncio
        from tools.actions import ActionDispatcher
        from voice.bridge import VoiceBridge
    except ImportError as exc:
        print(f"voice: disabled — import failed ({exc})", flush=True)
        return None

    dispatcher = ActionDispatcher(virtual_input=virtual_mouse)
    bridge = VoiceBridge(dispatcher)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(bridge.run())
        except Exception as exc:  # pragma: no cover
            print(f"voice: pipeline crashed ({exc})", flush=True)

    t = threading.Thread(target=_run, daemon=True, name="voice-bridge")
    t.start()
    print("voice: pipeline running in background thread", flush=True)
    return t


def run_onboarding(mouse) -> dict | None:
    """Run the guided capability wizard. Returns the new profile dict or None."""
    try:
        from onboarding import run as run_onboarding_flow
    except ImportError as exc:
        print(f"onboarding: module missing ({exc}) — skipping", flush=True)
        return None
    try:
        return run_onboarding_flow(mouse=mouse)
    except Exception as exc:  # pragma: no cover
        print(f"onboarding: failed ({exc}) — continuing without it", flush=True)
        return None


def resolve_mapping_path(args: argparse.Namespace, profile: dict | None) -> Path:
    """Pick which mapping file skeleton_preview should load.

    Order of precedence:
      1. --mapping CLI flag
      2. ~/.ember/profile.json if it exists
      3. repo-local mapping.json (legacy fallback)
    """
    if args.mapping:
        return Path(args.mapping)
    import profile as profile_mod
    if profile is not None and profile_mod.PROFILE_PATH.exists():
        return profile_mod.PROFILE_PATH
    return ROOT / "mapping.json"


def main() -> None:
    args = parse_args()

    # Autostart install/uninstall are one-shot commands.
    if args.install_autostart or args.uninstall_autostart:
        from cv import autostart  # type: ignore
        if args.install_autostart:
            path = autostart.install()
            print(f"autostart: installed at {path}", flush=True)
        else:
            removed = autostart.uninstall()
            print("autostart: removed" if removed else "autostart: nothing to remove", flush=True)
        return

    # Load existing profile (if any).
    import profile as profile_mod
    profile = profile_mod.load()
    if profile:
        print(f"profile: loaded from {profile_mod.PROFILE_PATH}", flush=True)
    else:
        print("profile: none yet — onboarding will run unless --no-onboard", flush=True)

    # Onboarding. Gets its own VirtualMouse (even though the wizard doesn't
    # move the OS cursor — cheaper to construct and close than to refactor).
    if should_onboard(args, profile):
        try:
            from cursor import VirtualMouse
            onboard_mouse = VirtualMouse()
            new_profile = run_onboarding(onboard_mouse)
            onboard_mouse.close()
            if new_profile is not None:
                profile = new_profile
        except Exception as exc:
            print(f"onboarding: skipped ({exc})", flush=True)

    # Voice pipeline is opt-in. Start before CV so the wake-word listener is hot.
    want_voice = voice_wanted(args, profile)
    voice_thread: threading.Thread | None = None
    if want_voice:
        # If the profile prefers voice-first (blind / motor-limited / keyboard-
        # less), auto-start + auto-restart the conversation so the user never
        # has to press a key to wake it.
        prefs = (profile or {}).get("preferences", {})
        if prefs.get("auto_wake"):
            os.environ["EMBER_VOICE_AUTO_WAKE"] = "1"
            print("voice: auto-wake enabled (user needs hands-free voice access)", flush=True)
        try:
            from cursor import VirtualMouse
            voice_mouse = VirtualMouse()
            voice_thread = start_voice_pipeline(voice_mouse)
        except Exception as exc:
            print(f"voice: VirtualMouse init failed ({exc})", flush=True)
    _ = voice_thread

    # Hand control to the CV pipeline's main() — blocks until the user quits.
    mapping_path = resolve_mapping_path(args, profile)
    print(f"cv: using mapping at {mapping_path}", flush=True)
    import skeleton_preview
    forwarded = [
        "--os", args.os,
        "--mapping", str(mapping_path),
        "--gestures", args.gestures,
    ]
    if args.no_preview:
        forwarded.append("--no-preview")
    elif args.pip:
        forwarded.append("--pip")
    sys.argv = [sys.argv[0]] + forwarded
    skeleton_preview.main()


if __name__ == "__main__":
    main()
