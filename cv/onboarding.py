"""First-launch onboarding overlay.

Fullscreen-ish OpenCV window that teaches the user Axis's basic loop:
  - Their head controls an on-screen cursor (not yet the OS cursor)
  - They pick which face gesture fires a click
  - Selection is written into mapping.json and the preview takes over

Driven entirely by head movement + dwell — no keyboard required.
Optional ElevenLabs TTS narration is played on entry to each step when
ELEVENLABS_API_KEY is set; otherwise runs silently.

Designed to be called once (on first launch) from axis.py.
Blocks until the user completes or presses Esc.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp

from filters import OneEuroFilter
from sources import nose_tip

WIN = "Axis — setup"
CAP_W, CAP_H = 640, 480
DISPLAY_W, DISPLAY_H = 1280, 720

DWELL_MS = 1500  # 1.5 seconds of cursor still over a tile to activate
CURSOR_SMOOTH_BETA = 0.08  # more responsive than the main preview during setup

# Pick-your-click options.  Must match source IDs emitted by cv/sources.py.
CLICK_CHOICES = [
    {
        "id": "mouth_click",
        "label": "Open your mouth",
        "sub": "Hold mouth open → click (hold to drag)",
        "source": "mouth",
        "action": "left_press",
        "params": {"threshold": 0.08},
    },
    {
        "id": "blink_click",
        "label": "Blink both eyes",
        "sub": "Close eyes ~200ms → click",
        "source": "blink",
        "action": "left_click",
        "params": {"ear_threshold": 0.18, "min_closed_ms": 200},
    },
    {
        "id": "brow_click",
        "label": "Raise eyebrows",
        "sub": "Raise brows noticeably → click",
        "source": "brow",
        "action": "left_click",
        "params": {"threshold": 0.06},
    },
]


def _speak_async(text: str) -> None:
    """Fire-and-forget TTS.  Silent if ElevenLabs isn't configured or deps missing."""
    if not os.getenv("ELEVENLABS_API_KEY"):
        return

    def _worker() -> None:
        try:
            import asyncio
            import io
            from tts.service import synthesize
            audio = asyncio.run(synthesize(text))
            # Play via miniaudio / simpleaudio / playsound if installed, otherwise swallow.
            try:
                import subprocess
                # ffplay is almost always available; -autoexit + -nodisp keeps it silent.
                p = subprocess.Popen(
                    ["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet", "-"],
                    stdin=subprocess.PIPE,
                )
                if p.stdin:
                    p.stdin.write(audio)
                    p.stdin.close()
            except FileNotFoundError:
                pass
        except Exception:
            pass  # narration is optional, never break onboarding

    threading.Thread(target=_worker, daemon=True).start()


def _tile_rects(n_tiles: int, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Evenly-spaced horizontal tiles in the bottom half of the screen."""
    margin = 40
    gap = 30
    tile_w = (w - 2 * margin - gap * (n_tiles - 1)) // n_tiles
    tile_h = h // 3
    y0 = h - tile_h - margin
    rects = []
    for i in range(n_tiles):
        x0 = margin + i * (tile_w + gap)
        rects.append((x0, y0, x0 + tile_w, y0 + tile_h))
    return rects


def _draw_tile(frame, rect, label: str, sub: str, hover_progress: float) -> None:
    """Draw a single choice tile with optional dwell-fill."""
    x0, y0, x1, y1 = rect
    # Base panel
    cv2.rectangle(frame, (x0, y0), (x1, y1), (30, 30, 30), -1)
    border_color = (80, 240, 140) if hover_progress > 0 else (80, 80, 80)
    thickness = 4 if hover_progress > 0 else 2
    cv2.rectangle(frame, (x0, y0), (x1, y1), border_color, thickness)
    # Dwell fill bar along the bottom
    if hover_progress > 0:
        fill_w = int((x1 - x0 - 20) * hover_progress)
        cv2.rectangle(frame, (x0 + 10, y1 - 18), (x0 + 10 + fill_w, y1 - 10), (80, 240, 140), -1)
    # Label
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    cv2.putText(
        frame, label,
        ((x0 + x1) // 2 - tw // 2, y0 + 50),
        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240), 2, cv2.LINE_AA,
    )
    (sw, sh), _ = cv2.getTextSize(sub, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.putText(
        frame, sub,
        ((x0 + x1) // 2 - sw // 2, y0 + 90),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA,
    )


def _point_in_rect(x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _write_mapping(mapping_path: Path, chosen: dict) -> None:
    """Update mapping.json: enable head_cursor + chosen click, disable the other clicks.

    Preserves any unrelated bindings the user may have added.
    """
    data: dict = {"bindings": []}
    if mapping_path.exists():
        try:
            data = json.loads(mapping_path.read_text())
        except json.JSONDecodeError:
            data = {"bindings": []}

    data.setdefault("version", 1)
    data.setdefault("cursor_sensitivity", 4000)
    data.setdefault("filter", {"min_cutoff": 1.0, "beta": 0.05})
    bindings: list[dict] = data.get("bindings", [])

    # 1. Make sure head_cursor exists and is enabled.
    head_binding = next((b for b in bindings if b.get("id") == "head_cursor"), None)
    if head_binding is None:
        bindings.append({
            "id": "head_cursor",
            "source": "nose",
            "action": "cursor_xy",
            "enabled": True,
            "invert_x": False,
            "invert_y": False,
        })
    else:
        head_binding["enabled"] = True

    # 2. Enable chosen click source, disable other click sources.
    chosen_ids = {c["id"] for c in CLICK_CHOICES}
    for b in bindings:
        if b.get("id") in chosen_ids:
            b["enabled"] = b["id"] == chosen["id"]

    # 3. If the chosen binding didn't exist yet, add it.
    if not any(b.get("id") == chosen["id"] for b in bindings):
        bindings.append({
            "id": chosen["id"],
            "source": chosen["source"],
            "action": chosen["action"],
            "enabled": True,
            **chosen["params"],
        })

    data["bindings"] = bindings
    mapping_path.write_text(json.dumps(data, indent=2))


def run(mouse=None, mapping_path: Path | None = None) -> None:
    """Entry point called by axis.py on first launch.

    `mouse` is accepted for future use (test-mode OS clicks) but unused here —
    onboarding draws its own cursor and doesn't touch the real OS.
    """
    mapping_path = Path(mapping_path or "mapping.json")

    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("onboarding: webcam unavailable — skipping", flush=True)
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    face = mp.solutions.face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=False)

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, DISPLAY_W, DISPLAY_H)

    # Two-phase flow: intro → choose click.
    phase = "intro"
    intro_enter_t = time.monotonic()
    _speak_async(
        "Welcome to Axis. Move your head to move the cursor, then hold it over "
        "the movement you want to use for clicking."
    )

    fx = OneEuroFilter(min_cutoff=1.0, beta=CURSOR_SMOOTH_BETA)
    fy = OneEuroFilter(min_cutoff=1.0, beta=CURSOR_SMOOTH_BETA)

    tiles = _tile_rects(len(CLICK_CHOICES), DISPLAY_W, DISPLAY_H)
    hover_idx: int | None = None
    hover_start = 0.0
    spoke_click_prompt = False

    chosen: dict | None = None
    exit_flash_until = 0.0

    try:
        while True:
            ok, raw = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(raw, 1)
            # Upscale to display resolution so overlays look clean.
            frame = cv2.resize(frame, (DISPLAY_W, DISPLAY_H))
            # Darken the video so text is readable over it.
            frame = cv2.addWeighted(frame, 0.35, frame, 0, 0)

            rgb = cv2.cvtColor(cv2.resize(raw, (CAP_W, CAP_H)), cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            face_res = face.process(rgb)

            now = time.monotonic()
            tip = nose_tip(face_res.multi_face_landmarks)
            cursor_xy: tuple[int, int] | None = None
            if tip is not None:
                # Mirror x to match the flipped display, then smooth.
                sx = fx.filter(1.0 - tip[0], now)
                sy = fy.filter(tip[1], now)
                cursor_xy = (int(sx * DISPLAY_W), int(sy * DISPLAY_H))

            if phase == "intro":
                _draw_intro(frame, intro_enter_t, now)
                # After 4 seconds or once we have a nose reading, advance.
                if (now - intro_enter_t) > 4.0 and cursor_xy is not None:
                    phase = "pick_click"
                    _speak_async(
                        "Pick the movement you'd like to use for clicking. "
                        "Hover the dot over your choice and hold still."
                    )

            elif phase == "pick_click":
                # Dwell logic.
                hover_now: int | None = None
                if cursor_xy is not None:
                    for i, rect in enumerate(tiles):
                        if _point_in_rect(cursor_xy[0], cursor_xy[1], rect):
                            hover_now = i
                            break

                if hover_now != hover_idx:
                    hover_idx = hover_now
                    hover_start = now

                # Draw everything.
                cv2.putText(
                    frame, "Pick your click",
                    (40, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (240, 240, 240), 2, cv2.LINE_AA,
                )
                cv2.putText(
                    frame, "Hover the dot over a tile and hold still",
                    (40, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (170, 170, 170), 1, cv2.LINE_AA,
                )

                for i, (rect, choice) in enumerate(zip(tiles, CLICK_CHOICES)):
                    progress = 0.0
                    if hover_idx == i:
                        progress = min(1.0, (now - hover_start) * 1000 / DWELL_MS)
                    _draw_tile(frame, rect, choice["label"], choice["sub"], progress)

                # Fire selection if dwell completed.
                if hover_idx is not None and (now - hover_start) * 1000 >= DWELL_MS:
                    chosen = CLICK_CHOICES[hover_idx]
                    _write_mapping(mapping_path, chosen)
                    _speak_async(f"Got it. {chosen['label']} is now your click.")
                    exit_flash_until = now + 2.5
                    phase = "done"

            elif phase == "done":
                cv2.putText(
                    frame, "You're set.",
                    (40, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (80, 240, 140), 3, cv2.LINE_AA,
                )
                cv2.putText(
                    frame,
                    f"Using '{chosen['label']}' for click. Axis is starting...",
                    (40, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2, cv2.LINE_AA,
                )
                if now >= exit_flash_until:
                    break

            # Always draw the cursor dot last so it's on top.
            if cursor_xy is not None:
                cv2.circle(frame, cursor_xy, 14, (80, 240, 140), 3)
                cv2.circle(frame, cursor_xy, 3, (80, 240, 140), -1)

            cv2.imshow(WIN, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # Esc — emergency cancel
                print("onboarding: cancelled by user (Esc)", flush=True)
                break
    finally:
        cap.release()
        cv2.destroyWindow(WIN)


def _draw_intro(frame, enter_t: float, now: float) -> None:
    alpha = min(1.0, (now - enter_t) / 0.6)
    def fade(c):  # noqa: E306
        return tuple(int(v * alpha) for v in c)
    cv2.putText(
        frame, "Welcome to Axis",
        (40, 120),
        cv2.FONT_HERSHEY_SIMPLEX, 1.6, fade((240, 240, 240)), 3, cv2.LINE_AA,
    )
    cv2.putText(
        frame, "Your body controls your computer.",
        (40, 170),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, fade((200, 200, 200)), 2, cv2.LINE_AA,
    )
    cv2.putText(
        frame, "Move your head to move the cursor.",
        (40, 220),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, fade((200, 200, 200)), 2, cv2.LINE_AA,
    )
    cv2.putText(
        frame, "The green dot follows your nose.",
        (40, 260),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, fade((170, 170, 170)), 1, cv2.LINE_AA,
    )
