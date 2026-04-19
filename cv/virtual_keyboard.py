"""Ember on-screen virtual keyboard.

Standalone subprocess. Shows a grid of keys at the bottom of the screen.
The user moves their cursor (head/hand driven) onto a key — after 600ms
of dwell, the key is typed via a dedicated uinput device.

Dwell-only is intentional: if the user *clicks* while over this window,
OpenCV takes focus and subsequent keystrokes would land here instead of
the app they were typing into. Hover-only keeps focus on the underlying
app so keys pass through cleanly.

Lifecycle: spawned/killed by tools.actions.ActionDispatcher._tool_keyboard.
SIGTERM shuts down cleanly.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

import cv2
import numpy as np
from evdev import UInput, ecodes as e


WIN = "Ember keyboard"
CELL_W = 70
CELL_H = 70
DEFAULT_DWELL_MS = 600
COOLDOWN_MS = 250  # after firing, require this much dwell-reset before refiring


# Layout rows. Each entry is (label, evdev_keycode[, span_cells]).
# Span defaults to 1. Space/backspace/enter get wider cells.
LAYOUT: list[list[tuple]] = [
    [("1", e.KEY_1), ("2", e.KEY_2), ("3", e.KEY_3), ("4", e.KEY_4), ("5", e.KEY_5),
     ("6", e.KEY_6), ("7", e.KEY_7), ("8", e.KEY_8), ("9", e.KEY_9), ("0", e.KEY_0),
     ("BS", e.KEY_BACKSPACE, 2)],
    [("q", e.KEY_Q), ("w", e.KEY_W), ("e", e.KEY_E), ("r", e.KEY_R), ("t", e.KEY_T),
     ("y", e.KEY_Y), ("u", e.KEY_U), ("i", e.KEY_I), ("o", e.KEY_O), ("p", e.KEY_P),
     ("ENT", e.KEY_ENTER, 2)],
    [("a", e.KEY_A), ("s", e.KEY_S), ("d", e.KEY_D), ("f", e.KEY_F), ("g", e.KEY_G),
     ("h", e.KEY_H), ("j", e.KEY_J), ("k", e.KEY_K), ("l", e.KEY_L),
     (",", e.KEY_COMMA), (".", e.KEY_DOT)],
    [("z", e.KEY_Z), ("x", e.KEY_X), ("c", e.KEY_C), ("v", e.KEY_V), ("b", e.KEY_B),
     ("n", e.KEY_N), ("m", e.KEY_M), ("-", e.KEY_MINUS), ("/", e.KEY_SLASH),
     ("TAB", e.KEY_TAB, 2)],
    [("SPACE", e.KEY_SPACE, 12)],
]


def build_geometry(layout: list[list[tuple]]) -> tuple[int, int, list[tuple]]:
    """Returns (width_px, height_px, keys) where keys = (label, keycode, x0, y0, x1, y1)."""
    max_cells = max(sum(_span(k) for k in row) for row in layout)
    width = max_cells * CELL_W
    height = len(layout) * CELL_H
    keys: list[tuple] = []
    for row_idx, row in enumerate(layout):
        row_cells = sum(_span(k) for k in row)
        x = (max_cells - row_cells) * CELL_W // 2
        y = row_idx * CELL_H
        for item in row:
            label, keycode = item[0], item[1]
            span = _span(item)
            keys.append((label, keycode, x, y, x + span * CELL_W, y + CELL_H))
            x += span * CELL_W
    return width, height, keys


def _span(item: tuple) -> int:
    return item[2] if len(item) == 3 else 1


def render(width: int, height: int, keys: list[tuple], hover: dict, now: float, dwell_ms: int) -> np.ndarray:
    frame = np.full((height, width, 3), 24, dtype=np.uint8)
    hovered = hover["key_idx"]
    fired = hover["fired"]
    elapsed_ms = (now - hover["since"]) * 1000 if hovered >= 0 else 0.0
    pct = min(1.0, elapsed_ms / dwell_ms) if hovered >= 0 and not fired else (1.0 if fired else 0.0)

    for i, (label, _kc, x0, y0, x1, y1) in enumerate(keys):
        base = (55, 55, 60)
        if i == hovered:
            if fired:
                fill = (80, 220, 140)
            else:
                # lerp from base to cyan-blue as dwell progresses
                r = int(55 + (220 - 55) * pct)
                g = int(55 + (180 - 55) * pct)
                b = int(60 + (80 - 60) * pct)
                fill = (b, g, r)
        else:
            fill = base
        cv2.rectangle(frame, (x0 + 3, y0 + 3), (x1 - 3, y1 - 3), fill, -1)
        cv2.rectangle(frame, (x0 + 3, y0 + 3), (x1 - 3, y1 - 3), (180, 180, 180), 1)

        # Progress bar under the hovered key
        if i == hovered and not fired:
            bar_h = 4
            bar_w = int((x1 - x0 - 6) * pct)
            cv2.rectangle(frame, (x0 + 3, y1 - 3 - bar_h), (x0 + 3 + bar_w, y1 - 3), (120, 220, 255), -1)

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
        tx = x0 + ((x1 - x0) - tw) // 2
        ty = y0 + ((y1 - y0) + th) // 2
        cv2.putText(frame, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                    (240, 240, 240), 2, cv2.LINE_AA)

    # Header strip
    cv2.rectangle(frame, (0, 0), (width, 4), (120, 220, 255), -1)
    return frame


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dwell-ms", type=int, default=DEFAULT_DWELL_MS)
    args = ap.parse_args()

    width, height, keys = build_geometry(LAYOUT)

    # One uinput device just for keyboard events. Separate from VirtualMouse
    # so CV pipeline continues to own the mouse and we own keys.
    try:
        keycodes = sorted({kc for _, kc, *_ in keys})
        ui = UInput({e.EV_KEY: keycodes}, name="ember-virtual-keyboard", version=0x1)
    except Exception as exc:
        print(f"keyboard: uinput failed ({exc}). "
              "Run: sudo chmod 0666 /dev/uinput", file=sys.stderr, flush=True)
        sys.exit(1)

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, width, height)
    try:
        cv2.setWindowProperty(WIN, cv2.WND_PROP_TOPMOST, 1.0)
    except Exception:
        pass

    # Try to park the window near the bottom of the screen. Without xdotool
    # we don't know exact screen size, so approximate.
    try:
        cv2.moveWindow(WIN, 200, 820)
    except Exception:
        pass

    hover = {"key_idx": -1, "since": 0.0, "fired": False, "last_fire": 0.0}

    def on_mouse(event, x, y, flags, param):
        if event != cv2.EVENT_MOUSEMOVE:
            return
        now = time.monotonic()
        idx = -1
        for i, (_, _, x0, y0, x1, y1) in enumerate(keys):
            if x0 <= x < x1 and y0 <= y < y1:
                idx = i
                break
        if idx != hover["key_idx"]:
            # Re-arm cooldown gate: if we just fired a key, require the user
            # to *leave* that key before the next press can arm.
            if hover["fired"] and idx >= 0:
                if (now - hover["last_fire"]) * 1000 < COOLDOWN_MS:
                    # too soon — park on "no hover" until cooldown passes
                    hover["key_idx"] = -1
                    hover["since"] = now
                    hover["fired"] = False
                    return
            hover["key_idx"] = idx
            hover["since"] = now
            hover["fired"] = False

    cv2.setMouseCallback(WIN, on_mouse)

    running = {"v": True}

    def _stop(_signum, _frame):
        running["v"] = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    print("keyboard: ready — dwell a key to type, SIGTERM to quit", flush=True)

    try:
        while running["v"]:
            now = time.monotonic()

            # Fire on dwell threshold.
            idx = hover["key_idx"]
            if idx >= 0 and not hover["fired"]:
                if (now - hover["since"]) * 1000 >= args.dwell_ms:
                    _, keycode, *_ = keys[idx]
                    try:
                        ui.write(e.EV_KEY, keycode, 1)
                        ui.syn()
                        ui.write(e.EV_KEY, keycode, 0)
                        ui.syn()
                    except Exception as exc:
                        print(f"keyboard: emit failed ({exc})", flush=True)
                    hover["fired"] = True
                    hover["last_fire"] = now

            frame = render(width, height, keys, hover, now, args.dwell_ms)
            cv2.imshow(WIN, frame)
            # 30 fps; also gives us a cancel path via 'q' if launched interactively.
            if (cv2.waitKey(30) & 0xFF) == ord("q"):
                break
    finally:
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        try:
            ui.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
