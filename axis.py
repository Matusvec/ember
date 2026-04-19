"""Axis — unified entry point.

Runs the CV pipeline (head/gesture → virtual cursor) and, optionally, the
ElevenLabs voice pipeline (wake word → conversation → action dispatcher).

Both layers share nothing except the Linux uinput driver — they each create a
virtual input device and write events to it independently.  That keeps the
30fps CV loop isolated from voice's 2-second network round trips.

Usage:
    python axis.py                 # CV only, onboarding runs on first launch
    python axis.py --voice         # CV + voice pipeline
    python axis.py --no-voice      # force voice off even if env says otherwise
    python axis.py --onboard       # re-run onboarding regardless of marker
    python axis.py --no-onboard    # skip onboarding even on first launch

Environment (loaded from .env via python-dotenv):
    ELEVENLABS_API_KEY       required for voice
    ELEVENLABS_AGENT_ID      required for voice
    PICOVOICE_ACCESS_KEY     required for wake word (fallback: press ENTER)
    AXIS_ENABLE_VOICE=1      equivalent to --voice
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
SETUP_MARKER = Path.home() / ".axis" / "setup_complete"

# cv/ modules do `from cursor import ...` — add cv/ to path so we can import them.
sys.path.insert(0, str(CV_DIR))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Axis — accessibility input layer")
    voice = ap.add_mutually_exclusive_group()
    voice.add_argument("--voice", action="store_true", help="enable ElevenLabs voice pipeline")
    voice.add_argument("--no-voice", action="store_true", help="force-disable voice pipeline")
    onboard = ap.add_mutually_exclusive_group()
    onboard.add_argument("--onboard", action="store_true", help="force re-run onboarding flow")
    onboard.add_argument("--no-onboard", action="store_true", help="skip onboarding")
    ap.add_argument(
        "--os",
        choices=["linux", "windows", "auto"],
        default="auto",
        help="Target OS for CV backend (default: auto-detect)",
    )
    ap.add_argument(
        "--mapping",
        default=str(ROOT / "mapping.json"),
        help="Path to mapping.json (default: %(default)s)",
    )
    ap.add_argument(
        "--gestures",
        default=str(ROOT / "gestures"),
        help="Directory for recorded gesture templates (default: %(default)s)",
    )
    return ap.parse_args()


def voice_wanted(args: argparse.Namespace) -> bool:
    if args.no_voice:
        return False
    if args.voice:
        return True
    # Fall back to env var — lets config choose without CLI flags.
    return os.getenv("AXIS_ENABLE_VOICE", "0") == "1"


def should_onboard(args: argparse.Namespace) -> bool:
    if args.no_onboard:
        return False
    if args.onboard:
        return True
    return not SETUP_MARKER.exists()


def start_voice_pipeline(virtual_mouse) -> threading.Thread | None:
    """Start the ElevenLabs voice pipeline in a background thread.

    Returns the thread handle so callers can see when it died.  Returns None if
    the pipeline can't start (missing deps or missing API key).
    """
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


def run_onboarding(mouse) -> None:
    """Run the first-launch onboarding flow.

    Imports onboarding module only when needed so the normal path has zero cost.
    On completion, writes the setup marker so onboarding doesn't re-run.
    """
    try:
        from onboarding import run as run_onboarding_flow
    except ImportError as exc:
        print(f"onboarding: module missing ({exc}) — skipping", flush=True)
        return

    try:
        run_onboarding_flow(mouse=mouse, mapping_path=ROOT / "mapping.json")
        SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SETUP_MARKER.touch()
        print(f"onboarding: complete — marker written to {SETUP_MARKER}", flush=True)
    except Exception as exc:  # pragma: no cover
        print(f"onboarding: failed ({exc}) — continuing without it", flush=True)


def main() -> None:
    args = parse_args()

    # Voice is opt-in. Start it before CV so wake-word listener is hot from the start.
    want_voice = voice_wanted(args)
    voice_thread: threading.Thread | None = None

    # CV pipeline (skeleton_preview.py) is the blocking main loop; run it directly.
    # It creates its own VirtualMouse when on Linux — voice gets its own, kernel handles
    # the two virtual devices cleanly.  Integration upgrade path: refactor to share one.
    if want_voice:
        try:
            from cursor import VirtualMouse
            voice_mouse = VirtualMouse()
            voice_thread = start_voice_pipeline(voice_mouse)
        except Exception as exc:
            print(f"voice: VirtualMouse init failed ({exc})", flush=True)

    if should_onboard(args):
        try:
            from cursor import VirtualMouse
            onboard_mouse = VirtualMouse()
            run_onboarding(onboard_mouse)
            onboard_mouse.close()
        except Exception as exc:
            print(f"onboarding: skipped ({exc})", flush=True)

    # Hand control to the CV pipeline's main() — blocks until the user quits.
    import skeleton_preview
    sys.argv = [sys.argv[0]] + [
        "--os", args.os,
        "--mapping", args.mapping,
        "--gestures", args.gestures,
    ]
    skeleton_preview.main()


if __name__ == "__main__":
    main()
