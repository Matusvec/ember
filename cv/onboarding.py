"""Ember onboarding -- guided capability wizard.

Walks a new user through discovering what they can do, then proposes a control
scheme and saves it to ~/.ember/profile.json. Runs in a native OpenCV window so
there is zero browser / permission friction.

Flow:
  1. welcome          -- "I'll find how you can control your computer."
  2. test_head        -- "Try moving your head"
  3. test_mouth       -- "Try opening your mouth"
  4. test_blink       -- "Try blinking both eyes"
  5. test_brow        -- "Try raising your eyebrows"
  6. test_hand        -- "Try holding up your hand"
  7. test_voice       -- "Try speaking any words"
  8. test_keyboard    -- "Try pressing any key"
  9. summary          -- shows detected capabilities + proposed mapping
 10. done             -- saves profile and exits; axis.py takes over

Every test auto-advances once a signal is seen OR after a timeout, and can
be skipped with Space. Esc aborts. No single input modality is required --
whatever the user can demonstrate is what they get.

Optional ElevenLabs narration plays at each step when ELEVENLABS_API_KEY is
set; silent otherwise.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import cv2
import mediapipe as mp

import profile as profile_mod
from filters import OneEuroFilter
from mic import MicMonitor
from narration import Narrator
from setup_agent import SetupAgent
from sources import (
    eye_aspect_ratio,
    eyebrow_raise,
    index_tip,
    mouth_ratio,
    nose_tip,
)

WIN = "Ember -- setup"
CAP_W, CAP_H = 640, 480
DISPLAY_W, DISPLAY_H = 1280, 720

# Per-test budget; tests auto-complete early on a clear signal.
TEST_DURATION_S = 14.0
WELCOME_S = 9.0
LINGER_AFTER_DETECT_S = 3.0
DONE_FLASH_S = 4.5

# Signal thresholds for "capable" detection.
HEAD_VARIANCE_THRESH = 0.005     # normalized nose-position variance
MOUTH_OPEN_THRESH = 0.09         # mouth_ratio peak
BLINK_EAR_THRESH = 0.17          # EAR below this = eyes closed
BROW_RAISE_DELTA = 0.012         # brow ratio spike vs baseline
HAND_FRAME_RATIO = 0.25          # hand detected in >= 25% of frames
VOICE_RMS_THRESH = 0.008         # mic RMS peak -- normal speech sits ~0.03-0.3


# ---- Design tokens ---------------------------------------------------------
#
# Colors are BGR (OpenCV convention). Palette tuned for a dark, warm UI that
# reads well over a dimmed webcam feed.

import numpy as np

FONT = cv2.FONT_HERSHEY_DUPLEX      # slightly nicer than SIMPLEX
FONT_LIGHT = cv2.FONT_HERSHEY_SIMPLEX

# Background + surfaces
BG_DIM       = (18, 16, 14)         # near-black, warm
CARD_BG      = (36, 32, 28)         # raised panel
CARD_BORDER  = (70, 64, 58)         # subtle panel border
CARD_BG_HI   = (48, 44, 38)         # hover / highlight variant

# Text
TEXT_PRIMARY   = (240, 238, 236)
TEXT_SECONDARY = (170, 162, 156)
TEXT_MUTED     = (110, 104, 100)
TEXT_DISABLED  = (80, 76, 72)

# Accents
ACCENT_EMBER  = (54, 130, 242)      # warm orange (BGR)
ACCENT_EMBER_D = (38, 90, 180)      # darker orange for fills
ACCENT_OK     = (120, 210, 130)     # soft green (BGR)
ACCENT_OK_D   = (80, 150, 90)
ACCENT_WARN   = (90, 170, 240)      # muted amber

# Narrator is set up once per run() and used in place of fire-and-forget TTS.
# Prompts are queued so they never overlap. When ELEVENLABS_API_KEY is missing,
# say() is a no-op.


# ---- Drawing helpers --------------------------------------------------------

def _text_size(text: str, scale: float, thick: int, font=FONT):
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    return tw, th


def _put_center(frame, text: str, y: int, scale: float, color, thick: int = 1,
                font=FONT) -> None:
    tw, _ = _text_size(text, scale, thick, font)
    x = (frame.shape[1] - tw) // 2
    cv2.putText(frame, text, (x, y), font, scale, color, thick, cv2.LINE_AA)


def _put(frame, text: str, xy: tuple[int, int], scale: float, color,
         thick: int = 1, font=FONT) -> None:
    cv2.putText(frame, text, xy, font, scale, color, thick, cv2.LINE_AA)


def _rounded_rect(frame, x0: int, y0: int, x1: int, y1: int, radius: int,
                  color, thickness: int = -1) -> None:
    """Filled (thickness=-1) or outlined rounded rectangle."""
    r = max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    if thickness == -1:
        # Body: two overlapping rects + four corner circles.
        cv2.rectangle(frame, (x0 + r, y0), (x1 - r, y1), color, -1)
        cv2.rectangle(frame, (x0, y0 + r), (x1, y1 - r), color, -1)
        cv2.circle(frame, (x0 + r, y0 + r), r, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (x1 - r, y0 + r), r, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (x0 + r, y1 - r), r, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (x1 - r, y1 - r), r, color, -1, cv2.LINE_AA)
    else:
        # Border: four straight segments + four arcs.
        cv2.line(frame, (x0 + r, y0), (x1 - r, y0), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (x0 + r, y1), (x1 - r, y1), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (x0, y0 + r), (x0, y1 - r), color, thickness, cv2.LINE_AA)
        cv2.line(frame, (x1, y0 + r), (x1, y1 - r), color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x0 + r, y0 + r), (r, r), 180, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x1 - r, y0 + r), (r, r), 270, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x1 - r, y1 - r), (r, r),   0, 0, 90, color, thickness, cv2.LINE_AA)
        cv2.ellipse(frame, (x0 + r, y1 - r), (r, r),  90, 0, 90, color, thickness, cv2.LINE_AA)


def _card(frame, x0: int, y0: int, x1: int, y1: int,
          bg=CARD_BG, border=CARD_BORDER, radius: int = 18,
          alpha: float = 0.92) -> None:
    """Draw a translucent rounded card with a subtle border."""
    overlay = frame.copy()
    _rounded_rect(overlay, x0, y0, x1, y1, radius, bg, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    _rounded_rect(frame, x0, y0, x1, y1, radius, border, 1)


def _progress_pill(frame, cx: int, cy: int, w: int, h: int, progress: float,
                   fill_color=ACCENT_EMBER, track_color=(40, 38, 36)) -> None:
    """Thin rounded progress bar used for timers + welcome countdown."""
    progress = max(0.0, min(1.0, progress))
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = cx + w // 2, cy + h // 2
    r = h // 2
    _rounded_rect(frame, x0, y0, x1, y1, r, track_color, -1)
    fill_w = int((x1 - x0) * progress)
    if fill_w > r:
        _rounded_rect(frame, x0, y0, x0 + fill_w, y1, r, fill_color, -1)


def _draw_progress_bar(frame, cx: int, cy: int, w: int, h: int, progress: float,
                       filled_color=ACCENT_EMBER) -> None:
    """Legacy name -- kept so older callers still work; delegates to pill style."""
    _progress_pill(frame, cx, cy, w, h, progress, filled_color)


def _draw_meter(frame, label: str, value: float, max_value: float, y: int,
                active: bool, label_col: int = 100, bar_col: int = 340,
                bar_w: int = 760, bar_h: int = 14) -> None:
    """Left-aligned label, large pill meter to the right."""
    color = ACCENT_OK if active else ACCENT_EMBER_D
    _put(frame, label, (label_col, y + 6), 0.66, TEXT_PRIMARY if active else TEXT_SECONDARY, 1)
    pct = max(0.0, min(1.0, value / max_value if max_value > 0 else 0.0))
    _progress_pill(frame, bar_col + bar_w // 2, y, bar_w, bar_h, pct, color)


def _darken(frame, factor: float = 0.22):
    return cv2.addWeighted(frame, factor, frame, 0, 0)


def _blur_bg(frame, ksize: int = 41):
    """Gaussian blur for a glassy background feel."""
    k = max(3, ksize | 1)  # must be odd
    return cv2.GaussianBlur(frame, (k, k), 0)


def _compose_bg(raw_bgr) -> np.ndarray:
    """Dim-+-blur the webcam so overlays read cleanly against it."""
    frame = cv2.resize(raw_bgr, (DISPLAY_W, DISPLAY_H))
    frame = _blur_bg(frame, 51)
    frame = _darken(frame, 0.22)
    # Subtle ember tint at the bottom so the UI doesn't feel cold.
    tint = np.zeros_like(frame)
    tint[:, :] = BG_DIM
    frame = cv2.addWeighted(frame, 0.85, tint, 0.15, 0)
    return frame


def _draw_step_dots(frame, total: int, current: int, y: int = 28) -> None:
    """Little progress dots at the top so the user knows where they are."""
    gap = 14
    r = 4
    total_w = total * (2 * r) + (total - 1) * gap
    x = (DISPLAY_W - total_w) // 2
    for i in range(total):
        cx = x + r + i * (2 * r + gap)
        if i < current:
            cv2.circle(frame, (cx, y), r, ACCENT_EMBER, -1, cv2.LINE_AA)
        elif i == current:
            cv2.circle(frame, (cx, y), r + 2, ACCENT_EMBER, -1, cv2.LINE_AA)
        else:
            cv2.circle(frame, (cx, y), r, CARD_BORDER, -1, cv2.LINE_AA)


def _draw_chip(frame, text: str, cx: int, cy: int,
               bg=CARD_BG_HI, fg=TEXT_PRIMARY, accent=None) -> None:
    """Small pill-shaped status chip."""
    tw, th = _text_size(text, 0.6, 1)
    pad_x, pad_y = 18, 12
    w, h = tw + pad_x * 2, th + pad_y * 2
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = cx + w // 2, cy + h // 2
    _rounded_rect(frame, x0, y0, x1, y1, h // 2, bg, -1)
    if accent is not None:
        cv2.circle(frame, (x0 + 18, cy), 5, accent, -1, cv2.LINE_AA)
        _put(frame, text, (x0 + 32, cy + 6), 0.6, fg, 1)
    else:
        _put(frame, text, (cx - tw // 2, cy + 6), 0.6, fg, 1)


def _draw_footer(frame, lines: list[str]) -> None:
    """Subtle bottom hint line."""
    y = DISPLAY_H - 28
    text = "   |   ".join(lines)
    tw, _ = _text_size(text, 0.5, 1)
    _put(frame, text, ((DISPLAY_W - tw) // 2, y), 0.5, TEXT_MUTED, 1)


def _draw_wordmark(frame, x: int, y: int) -> None:
    """Ember wordmark + tiny accent glyph."""
    cv2.circle(frame, (x, y - 6), 6, ACCENT_EMBER, -1, cv2.LINE_AA)
    _put(frame, "Ember", (x + 18, y), 0.8, TEXT_PRIMARY, 1)


# ---- Test definitions -------------------------------------------------------

# Each test dict:
#   id:          capability key written to profile
#   title:       bold prompt
#   hint:        subtitle
#   meter_label: what the live meter shows (None = no meter)
#   meter_max:   scale for the meter
#   detect:      function(state) -> (current_value, is_capable_now)

class TestState:
    """Per-test rolling state -- signal buffers and detection flags."""
    def __init__(self, test_id: str, started_at: float) -> None:
        self.id = test_id
        self.t_start = started_at
        self.detected = False
        self.peak_value = 0.0
        # test-specific buffers
        self.nose_xs: list[float] = []
        self.nose_ys: list[float] = []
        self.brow_baseline: float | None = None
        self.brow_samples: list[float] = []
        # Blink: adaptive baseline so we detect a RELATIVE drop in EAR
        # instead of an absolute threshold (which varies per person). The
        # onboarding test only counts DELIBERATE blinks (deep closure held
        # for a beat) so a user who naturally blinks during the test isn't
        # falsely marked blink-capable.
        self.ear_baseline: float | None = None
        self.ear_samples: list[float] = []
        self.blinks_seen = 0
        self.last_ear_above = True
        self.closure_started_at: float | None = None
        self.current_blink_scored = False
        self.hand_frames = 0
        self.total_frames = 0
        self.keyboard_pressed = False


def _update_test(test_id: str, st: TestState, face_lms, hand_lms, key_pressed: int,
                 mic: MicMonitor) -> tuple[float, bool]:
    """Per-frame update. Returns (display_value, capable_now)."""
    now = time.monotonic()
    st.total_frames += 1

    if test_id == "head":
        tip = nose_tip(face_lms)
        if tip is not None:
            st.nose_xs.append(tip[0])
            st.nose_ys.append(tip[1])
            # use last ~2 seconds of samples
            if len(st.nose_xs) > 60:
                st.nose_xs = st.nose_xs[-60:]
                st.nose_ys = st.nose_ys[-60:]
            if len(st.nose_xs) >= 10:
                # range (max-min) is a more robust "did they move" than variance
                rng = max(max(st.nose_xs) - min(st.nose_xs),
                          max(st.nose_ys) - min(st.nose_ys))
                st.peak_value = max(st.peak_value, rng)
                st.detected = st.detected or rng > HEAD_VARIANCE_THRESH * 10
                return rng, st.detected
        return 0.0, st.detected

    if test_id == "mouth":
        v = mouth_ratio(face_lms)
        if v is not None:
            st.peak_value = max(st.peak_value, v)
            if v > MOUTH_OPEN_THRESH:
                st.detected = True
            return v, st.detected
        return 0.0, st.detected

    if test_id == "blink":
        ear = eye_aspect_ratio(face_lms, "both")
        if ear is not None:
            # Baseline = median of first ~1.2s open-eye samples.
            st.ear_samples.append(ear)
            if len(st.ear_samples) > 120:
                st.ear_samples = st.ear_samples[-120:]
            if st.ear_baseline is None and (now - st.t_start) > 1.2 and len(st.ear_samples) > 10:
                sorted_s = sorted(st.ear_samples)
                st.ear_baseline = sorted_s[len(sorted_s) // 2]
            # Single blink passes: EAR drops below 70% of baseline on the
            # falling edge. Lenient on purpose — a natural blink works.
            drop_thresh = (st.ear_baseline * 0.70) if st.ear_baseline else BLINK_EAR_THRESH
            closure = max(0.0, min(1.0,
                ((st.ear_baseline or 0.28) - ear) /
                ((st.ear_baseline or 0.28) * 0.6 + 1e-6)
            ))
            st.peak_value = max(st.peak_value, closure)
            is_closed = ear < drop_thresh
            if is_closed and st.last_ear_above:
                st.blinks_seen += 1
            st.last_ear_above = not is_closed
            if st.blinks_seen >= 1:
                st.detected = True
            return closure, st.detected
        return 0.0, st.detected

    if test_id == "brow":
        v = eyebrow_raise(face_lms)
        if v is not None:
            st.brow_samples.append(v)
            if len(st.brow_samples) > 90:
                st.brow_samples = st.brow_samples[-90:]
            # first 0.8s are baseline
            if st.brow_baseline is None and (now - st.t_start) > 0.8:
                st.brow_baseline = sum(st.brow_samples) / len(st.brow_samples)
            if st.brow_baseline is not None:
                delta = v - st.brow_baseline
                st.peak_value = max(st.peak_value, delta)
                if delta > BROW_RAISE_DELTA:
                    st.detected = True
                return max(0.0, delta), st.detected
            return 0.0, st.detected
        return 0.0, st.detected

    if test_id == "hand":
        if hand_lms is not None and len(hand_lms) > 0:
            st.hand_frames += 1
        ratio = st.hand_frames / max(1, st.total_frames)
        st.peak_value = max(st.peak_value, ratio)
        if ratio > HAND_FRAME_RATIO and st.total_frames > 20:
            st.detected = True
        return ratio, st.detected

    if test_id == "voice":
        peak = mic.peak_rms_since(st.t_start)
        st.peak_value = max(st.peak_value, peak)
        if peak > VOICE_RMS_THRESH:
            st.detected = True
        return peak, st.detected

    if test_id == "keyboard":
        # Any key other than ESC/Space/255 counts -- but during tests we also
        # accept Space as "skip", so we check for any printable/arrow key.
        if key_pressed not in (255, -1, 27, 32):
            st.keyboard_pressed = True
            st.detected = True
        return 1.0 if st.keyboard_pressed else 0.0, st.detected

    return 0.0, False


TESTS: list[dict[str, Any]] = [
    {
        "id": "head",
        "title": "Try moving your head",
        "hint": "Tilt, nod, or just shift side to side -- anything that moves",
        "meter_label": "head motion range",
        "meter_max": 0.12,
    },
    {
        "id": "mouth",
        "title": "Try opening your mouth",
        "hint": "Open it wide once -- like saying \"ah\"",
        "meter_label": "mouth opening",
        "meter_max": 0.25,
    },
    {
        "id": "blink",
        "title": "Try blinking both eyes",
        "hint": "A normal blink -- close both eyes, then open.",
        "meter_label": "eye closure",
        "meter_max": 0.25,
    },
    {
        "id": "brow",
        "title": "Try raising your eyebrows",
        "hint": "Lift your brows like you're surprised",
        "meter_label": "brow lift",
        "meter_max": 0.04,
    },
    {
        "id": "hand",
        "title": "Try holding up your hand",
        "hint": "Put your hand into the camera view -- either hand, palm open",
        "meter_label": "hand in frame",
        "meter_max": 1.0,
    },
    {
        "id": "voice",
        "title": "Try speaking any words",
        "hint": "Say hi, count to three, anything at all",
        "meter_label": "mic input",
        "meter_max": 0.15,
    },
    {
        "id": "keyboard",
        "title": "Try pressing any key",
        "hint": "Any letter or number (Esc or Space will skip instead)",
        "meter_label": "key pressed",
        "meter_max": 1.0,
    },
]

TEST_SPOKEN: dict[str, str] = {
    "head": "Try moving your head. Tilt it side to side, or just shift a little.",
    "mouth": "Try opening your mouth. Open wide, like saying ah.",
    "blink": "Try blinking both eyes.",
    "brow": "Try raising your eyebrows.",
    "hand": "Try holding up your hand into the camera view.",
    "voice": "Try speaking any words.",
    "keyboard": "Try pressing any key on the keyboard.",
}


# ---- Phase: welcome ---------------------------------------------------------

def _draw_welcome(frame, elapsed: float) -> None:
    alpha = min(1.0, elapsed / 0.8)
    def fade(c):  # noqa: E306
        return tuple(int(v * alpha) for v in c)

    _draw_wordmark(frame, 60, 70)

    _put_center(frame, "Welcome to Ember", 260, 2.0, fade(TEXT_PRIMARY), 2)
    _put_center(frame, "Adaptive control for your computer.", 315, 0.75,
                fade(TEXT_SECONDARY), 1, font=FONT_LIGHT)

    _put_center(frame, "I'll figure out how you like to interact --",
                400, 0.7, fade(TEXT_SECONDARY), 1, font=FONT_LIGHT)
    _put_center(frame, "whatever you can do becomes your input.",
                432, 0.7, fade(TEXT_SECONDARY), 1, font=FONT_LIGHT)

    # countdown ring + label
    _put_center(frame, "Getting ready...", 590, 0.55, TEXT_MUTED, 1, font=FONT_LIGHT)
    _progress_pill(frame, DISPLAY_W // 2, 620, 320, 8,
                   min(1.0, elapsed / WELCOME_S), ACCENT_EMBER)


# ---- Phase: capability test -------------------------------------------------

def _draw_test(frame, test: dict[str, Any], st: TestState, value: float,
               progress: float, step_idx: int, step_total: int) -> None:
    _draw_wordmark(frame, 60, 46)
    _draw_step_dots(frame, step_total, step_idx, y=44)

    # Hero card -- contains prompt, meter, chip.
    card_x0, card_y0 = 120, 130
    card_x1, card_y1 = DISPLAY_W - 120, 540
    _card(frame, card_x0, card_y0, card_x1, card_y1, radius=24, alpha=0.88)

    # Step label (tiny, monospace-ish caps)
    label = f"step {step_idx + 1} of {step_total}".upper()
    _put(frame, label, (card_x0 + 40, card_y0 + 52), 0.45,
         ACCENT_EMBER, 1, font=FONT_LIGHT)

    # Title & hint
    _put(frame, test["title"], (card_x0 + 40, card_y0 + 108), 1.1, TEXT_PRIMARY, 1)
    _put(frame, test["hint"], (card_x0 + 40, card_y0 + 148), 0.6,
         TEXT_SECONDARY, 1, font=FONT_LIGHT)

    # Remaining-time pill
    _put(frame, "time left", (card_x0 + 40, card_y0 + 200), 0.48,
         TEXT_MUTED, 1, font=FONT_LIGHT)
    _progress_pill(frame, (card_x0 + card_x1) // 2, card_y0 + 230,
                   card_x1 - card_x0 - 80, 8, 1 - progress, ACCENT_EMBER_D)

    # Live signal meter
    _put(frame, test["meter_label"], (card_x0 + 40, card_y0 + 290), 0.55,
         TEXT_SECONDARY, 1, font=FONT_LIGHT)
    pct = max(0.0, min(1.0, value / test["meter_max"] if test["meter_max"] > 0 else 0.0))
    _progress_pill(frame, (card_x0 + card_x1) // 2, card_y0 + 320,
                   card_x1 - card_x0 - 80, 14,
                   pct, ACCENT_OK if st.detected else ACCENT_EMBER)

    # Status chip
    if st.detected:
        _draw_chip(frame, "detected", DISPLAY_W // 2, card_y1 - 40,
                   bg=(44, 78, 48), fg=(220, 240, 220), accent=ACCENT_OK)
    else:
        _draw_chip(frame, "listening...", DISPLAY_W // 2, card_y1 - 40,
                   bg=CARD_BG_HI, fg=TEXT_SECONDARY, accent=ACCENT_EMBER)

    _draw_footer(frame, ["space  skip", "esc  quit"])


# ---- Phase: summary ---------------------------------------------------------

CAP_LABELS = {
    "head":     "Head motion",
    "mouth":    "Open mouth",
    "blink":    "Blink",
    "brow":     "Eyebrow raise",
    "hand":     "Hand / finger",
    "voice":    "Voice",
    "keyboard": "Keyboard",
}


def _draw_summary(frame, caps: dict[str, bool], proposed: list[dict[str, Any]],
                  confirm_progress: float, cap_progress: float) -> None:
    _draw_wordmark(frame, 60, 46)
    _put_center(frame, "Here's what I found", 110, 1.3, TEXT_PRIMARY, 1)
    _put_center(frame, "Review your setup, then confirm or start over.",
                146, 0.56, TEXT_SECONDARY, 1, font=FONT_LIGHT)

    # Two cards side by side.
    gap = 28
    card_w = (DISPLAY_W - 120 - gap) // 2
    left_x0 = 60
    right_x0 = left_x0 + card_w + gap
    card_y0, card_y1 = 190, 540

    # ----- Left: capabilities -----
    _card(frame, left_x0, card_y0, left_x0 + card_w, card_y1, radius=22)
    _put(frame, "YOU CAN USE", (left_x0 + 28, card_y0 + 42), 0.48, ACCENT_EMBER, 1, font=FONT_LIGHT)
    y = card_y0 + 84
    for cid in profile_mod.CAPABILITY_IDS:
        ok = caps.get(cid, False)
        if ok:
            cv2.circle(frame, (left_x0 + 40, y - 6), 6, ACCENT_OK, -1, cv2.LINE_AA)
            _put(frame, CAP_LABELS[cid], (left_x0 + 60, y), 0.6, TEXT_PRIMARY, 1)
        else:
            cv2.circle(frame, (left_x0 + 40, y - 6), 5, CARD_BORDER, 1, cv2.LINE_AA)
            _put(frame, CAP_LABELS[cid], (left_x0 + 60, y), 0.58, TEXT_DISABLED, 1, font=FONT_LIGHT)
        y += 32

    # ----- Right: proposed mapping -----
    _card(frame, right_x0, card_y0, right_x0 + card_w, card_y1, radius=22)
    _put(frame, "EMBER WILL SET UP", (right_x0 + 28, card_y0 + 42),
         0.48, ACCENT_EMBER, 1, font=FONT_LIGHT)
    y = card_y0 + 84
    active = [b for b in proposed if b.get("enabled")]
    if not active:
        _put(frame, "nothing detected -- try again",
             (right_x0 + 28, y), 0.58, (170, 130, 130), 1, font=FONT_LIGHT)
    else:
        for b in active:
            desc = _describe_binding(b)
            _put(frame, ">", (right_x0 + 32, y), 0.7, ACCENT_EMBER, 1)
            _put(frame, desc, (right_x0 + 56, y), 0.58, TEXT_PRIMARY, 1)
            y += 34

    # Confirm / redo buttons (dwell zones or keyboard)
    _draw_summary_buttons(frame, confirm_progress, cap_progress)


def _read_live_signals(face_lms, hand_lms) -> dict[str, float]:
    """Snapshot of every trackable signal, normalized 0..1 for meters."""
    out: dict[str, float] = {}
    tip = nose_tip(face_lms)
    if tip is not None:
        out["head"] = 1.0  # presence flag; motion handled elsewhere
    mouth = mouth_ratio(face_lms)
    if mouth is not None:
        out["mouth"] = float(mouth)
    ear = eye_aspect_ratio(face_lms, "both")
    if ear is not None:
        # "eye closure" -- higher when closed
        out["blink"] = max(0.0, 0.3 - float(ear))
    brow = eyebrow_raise(face_lms)
    if brow is not None:
        out["brow"] = float(brow)
    if hand_lms is not None and len(hand_lms) > 0:
        out["hand"] = 1.0
    else:
        out["hand"] = 0.0
    return out


def _live_pulse(frame, cx: int, cy: int, elapsed: float,
                color=ACCENT_OK, label: str = "live") -> None:
    """Recording-dot-style pulsing indicator."""
    import math
    phase = 0.5 + 0.5 * math.sin(elapsed * 3.5)
    outer = int(14 + 6 * phase)
    inner = 8
    cv2.circle(frame, (cx, cy), outer, (color[0] // 4, color[1] // 4, color[2] // 4),
               -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), inner, color, -1, cv2.LINE_AA)
    _put(frame, label, (cx - 20, cy + 36), 0.5, TEXT_SECONDARY, 1, font=FONT_LIGHT)


def _draw_explore(frame, signals: dict[str, float], elapsed: float) -> None:
    """Live meters for every movement Ember can track."""
    _draw_wordmark(frame, 60, 46)
    _put_center(frame, "Exploration", 110, 1.3, TEXT_PRIMARY, 1)
    _put_center(frame, "Move anything you can -- I'll show you what I see.",
                146, 0.56, TEXT_SECONDARY, 1, font=FONT_LIGHT)

    card_x0, card_y0 = 120, 190
    card_x1, card_y1 = DISPLAY_W - 120, 560
    _card(frame, card_x0, card_y0, card_x1, card_y1, radius=22)

    rows = [
        ("head",  "Head present",   1.0),
        ("mouth", "Mouth opening",  0.25),
        ("blink", "Eye closure",    0.22),
        ("brow",  "Eyebrow lift",   0.04),
        ("hand",  "Hand in view",   1.0),
    ]
    y = card_y0 + 60
    for sid, label, max_v in rows:
        v = signals.get(sid, 0.0)
        active = v > {"head": 0.5, "mouth": 0.07, "blink": 0.07,
                      "brow": 0.005, "hand": 0.5}.get(sid, 0.0)
        _draw_meter(frame, label, v, max_v, y, active=active,
                    label_col=card_x0 + 40, bar_col=card_x0 + 260,
                    bar_w=card_x1 - card_x0 - 300, bar_h=12)
        y += 58

    _live_pulse(frame, DISPLAY_W - 80, DISPLAY_H - 80, elapsed,
                color=ACCENT_OK, label="live")
    _draw_footer(frame, ["say \"done\" to go back", "esc  back"])


def _draw_converse(frame, agent: SetupAgent, elapsed_since_enter: float) -> None:
    """Live summary of the voice setup session."""
    _draw_wordmark(frame, 60, 46)
    _put_center(frame, "Just talk to me", 110, 1.35, TEXT_PRIMARY, 1)
    _put_center(frame,
                "Interrupt anytime  |  say \"save it\" when you're done",
                146, 0.56, TEXT_SECONDARY, 1, font=FONT_LIGHT)

    # Mapping card on the left, speech bubble on the right.
    gap = 28
    card_w_left = 520
    left_x0 = 60
    right_x0 = left_x0 + card_w_left + gap
    right_x1 = DISPLAY_W - 60
    card_y0, card_y1 = 190, 540

    # Left -- current mapping
    _card(frame, left_x0, card_y0, left_x0 + card_w_left, card_y1, radius=22)
    _put(frame, "CURRENT MAPPING", (left_x0 + 28, card_y0 + 42),
         0.48, ACCENT_EMBER, 1, font=FONT_LIGHT)
    y = card_y0 + 84
    active = [b for b in agent.draft.bindings if b.get("enabled")]
    if not active:
        _put(frame, "nothing yet", (left_x0 + 28, y),
             0.58, TEXT_MUTED, 1, font=FONT_LIGHT)
    else:
        for b in active:
            _put(frame, ">", (left_x0 + 32, y), 0.7, ACCENT_EMBER, 1)
            _put(frame, _describe_binding(b),
                 (left_x0 + 56, y), 0.58, TEXT_PRIMARY, 1)
            y += 34
    if agent.draft.voice_enabled:
        _put(frame, ">", (left_x0 + 32, y), 0.7, ACCENT_EMBER, 1)
        _put(frame, "voice commands enabled",
             (left_x0 + 56, y), 0.58, TEXT_PRIMARY, 1)

    # Right -- agent speech bubble + pulsing mic
    _card(frame, right_x0, card_y0, right_x1, card_y1, radius=22)
    _put(frame, "EMBER", (right_x0 + 28, card_y0 + 42),
         0.48, ACCENT_EMBER, 1, font=FONT_LIGHT)

    last = agent.last_agent_text or "..."
    # Wrap long lines manually.
    words = last.split()
    lines: list[str] = []
    cur = ""
    max_w = right_x1 - right_x0 - 56
    for w in words:
        trial = (cur + " " + w).strip()
        tw, _ = _text_size(trial, 0.6, 1, font=FONT_LIGHT)
        if tw > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    ly = card_y0 + 96
    for line in lines[:6]:
        _put(frame, line, (right_x0 + 28, ly), 0.6, TEXT_PRIMARY, 1, font=FONT_LIGHT)
        ly += 32

    # Pulsing mic indicator bottom-right of card.
    _live_pulse(frame, right_x1 - 70, card_y1 - 60, elapsed_since_enter,
                color=ACCENT_OK, label="listening")

    _draw_footer(frame, ["esc  skip voice setup"])


def _describe_binding(b: dict[str, Any]) -> str:
    src = b.get("source", "?")
    act = b.get("action", "?")
    label_src = {
        "nose": "head", "mouth": "mouth", "blink": "blink",
        "brow": "eyebrows", "index_tip": "finger",
    }.get(src, src)
    label_act = {
        "cursor_xy": "-> move cursor",
        "left_press": "-> click (hold to drag)",
        "left_click": "-> click",
        "right_click": "-> right-click",
    }.get(act, f"-> {act}")
    return f"{label_src} {label_act}"


def _draw_button(frame, x0: int, y0: int, x1: int, y1: int, label: str,
                 sub: str, progress: float, accent) -> None:
    """Pill-shaped button with dwell progress + label + subline."""
    _card(frame, x0, y0, x1, y1, bg=CARD_BG_HI, border=accent, radius=(y1 - y0) // 3,
          alpha=0.94)
    # Progress fill lives behind the label.
    if progress > 0:
        inner_x0, inner_y0 = x0 + 6, y0 + 6
        inner_x1, inner_y1 = x1 - 6, y1 - 6
        fill_w = int((inner_x1 - inner_x0) * progress)
        if fill_w > 0:
            _rounded_rect(frame, inner_x0, inner_y0, inner_x0 + fill_w, inner_y1,
                          (inner_y1 - inner_y0) // 2, accent, -1)
    # Label + subline centered.
    tw, th = _text_size(label, 0.82, 1)
    lx = (x0 + x1) // 2 - tw // 2
    ly = (y0 + y1) // 2 + 2
    _put(frame, label, (lx, ly), 0.82, TEXT_PRIMARY, 1)
    tw2, _ = _text_size(sub, 0.45, 1, font=FONT_LIGHT)
    _put(frame, sub, ((x0 + x1) // 2 - tw2 // 2, ly + 26), 0.45,
         TEXT_SECONDARY, 1, font=FONT_LIGHT)


def _draw_summary_buttons(frame, confirm_progress: float, redo_progress: float) -> None:
    bw, bh = 300, 78
    y0 = DISPLAY_H - 110
    # Redo (left)
    _draw_button(frame, 60, y0, 60 + bw, y0 + bh, "Start over",
                 "press R  |  look left", redo_progress, ACCENT_WARN)
    # Confirm (right)
    _draw_button(frame, DISPLAY_W - 60 - bw, y0, DISPLAY_W - 60, y0 + bh,
                 "Looks good", "press Enter  |  look right",
                 confirm_progress, ACCENT_OK)


def _draw_summary_buttons_old(frame, confirm_progress: float, redo_progress: float) -> None:
    bx = DISPLAY_W - 330
    by = DISPLAY_H - 110
    bw, bh = 260, 70
    border = (80, 240, 140) if confirm_progress > 0 else (100, 160, 120)
    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (20, 40, 25), -1)
    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), border, 3)
    if confirm_progress > 0:
        fill_w = int((bw - 20) * confirm_progress)
        cv2.rectangle(frame, (bx + 10, by + bh - 14),
                      (bx + 10 + fill_w, by + bh - 8), (80, 240, 140), -1)
    cv2.putText(frame, "Looks good", (bx + 45, by + 35), FONT, 0.8, (220, 255, 220), 2, cv2.LINE_AA)
    cv2.putText(frame, "Enter  >  hover right", (bx + 45, by + 58),
                FONT, 0.45, (160, 200, 170), 1, cv2.LINE_AA)

    # Redo (R / look-left)
    rx = 70
    ry = DISPLAY_H - 110
    border = (240, 180, 80) if redo_progress > 0 else (160, 130, 90)
    cv2.rectangle(frame, (rx, ry), (rx + bw, ry + bh), (40, 30, 15), -1)
    cv2.rectangle(frame, (rx, ry), (rx + bw, ry + bh), border, 3)
    if redo_progress > 0:
        fill_w = int((bw - 20) * redo_progress)
        cv2.rectangle(frame, (rx + 10, ry + bh - 14),
                      (rx + 10 + fill_w, ry + bh - 8), (240, 180, 80), -1)
    cv2.putText(frame, "Redo setup", (rx + 45, ry + 35), FONT, 0.8, (255, 230, 180), 2, cv2.LINE_AA)
    cv2.putText(frame, "R  >  hover left", (rx + 45, ry + 58),
                FONT, 0.45, (200, 180, 140), 1, cv2.LINE_AA)


# ---- Main run ---------------------------------------------------------------

def run(mouse=None, mapping_path: Path | None = None) -> dict[str, Any] | None:
    """Run the guided setup. Returns the saved profile, or None on cancel.

    `mouse` is accepted for API compatibility with the older onboarding entry
    point -- this wizard does not touch the OS cursor.
    `mapping_path` is ignored (profile goes to ~/.ember/profile.json).
    """
    _ = mouse
    _ = mapping_path

    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("onboarding: webcam unavailable -- skipping", flush=True)
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    face = mp.solutions.face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=False)
    hands = mp.solutions.hands.Hands(max_num_hands=1, model_complexity=0)

    mic = MicMonitor()
    mic.start()

    narrator = Narrator()
    narrator.start()

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, DISPLAY_W, DISPLAY_H)

    capabilities: dict[str, bool] = {cid: False for cid in profile_mod.CAPABILITY_IDS}

    # A tiny head-cursor for summary button hover, only active if head passes.
    fx = OneEuroFilter(min_cutoff=1.0, beta=0.08)
    fy = OneEuroFilter(min_cutoff=1.0, beta=0.08)

    phase = "welcome"
    phase_start = time.monotonic()
    narrator.say("Welcome to Ember. I'll figure out how you like to use a computer.")

    test_idx = 0
    test_state: TestState | None = None

    confirm_start = 0.0
    redo_start = 0.0
    result_profile: dict[str, Any] | None = None

    # Conversational setup state (only used if voice is detected)
    agent: SetupAgent | None = None
    agent_bindings_snapshot: list[dict[str, Any]] = []
    agent_voice_snapshot: bool = False

    # If the agent triggers a single test, we remember the phase to return to.
    single_test_return_to: str | None = None
    explore_start: float = 0.0

    try:
        while True:
            ok, raw = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame_small = cv2.flip(raw, 1)
            display = _compose_bg(frame_small)

            rgb = cv2.cvtColor(cv2.resize(raw, (CAP_W, CAP_H)), cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            face_res = face.process(rgb)
            hand_res = hands.process(rgb)

            now = time.monotonic()

            # Key poll -- used per-phase.
            key = cv2.waitKey(1) & 0xFF
            if key == 27:  # Esc
                print("onboarding: cancelled by user (Esc)", flush=True)
                return None

            # Cursor for summary buttons (head capable only)
            cursor_xy: tuple[int, int] | None = None
            if capabilities.get("head"):
                tip = nose_tip(face_res.multi_face_landmarks)
                if tip is not None:
                    sx = fx.filter(1.0 - tip[0], now)
                    sy = fy.filter(tip[1], now)
                    cursor_xy = (int(sx * DISPLAY_W), int(sy * DISPLAY_H))

            if phase == "welcome":
                _draw_welcome(display, now - phase_start)
                if (now - phase_start) > WELCOME_S or key != 255:
                    phase = "test"
                    test_idx = 0
                    test_state = TestState(TESTS[0]["id"], now)
                    narrator.say(TEST_SPOKEN[TESTS[0]["id"]])

            elif phase == "test":
                test = TESTS[test_idx]
                assert test_state is not None
                elapsed = now - test_state.t_start
                progress = min(1.0, elapsed / TEST_DURATION_S)

                value, capable_now = _update_test(
                    test["id"], test_state,
                    face_res.multi_face_landmarks,
                    hand_res.multi_hand_landmarks,
                    key, mic,
                )

                _draw_test(display, test, test_state, value, progress,
                           step_idx=test_idx, step_total=len(TESTS))

                # Advance: on timeout, OR on stable detection (give them a sec
                # to see the [ok]), OR on space-skip.
                skip = key == 32  # space
                linger_done = test_state.detected and elapsed > LINGER_AFTER_DETECT_S
                if skip or linger_done or progress >= 1.0:
                    capabilities[test["id"]] = test_state.detected
                    # Single-test-on-demand (agent-triggered): report back, return.
                    if single_test_return_to is not None and agent is not None:
                        agent.draft.last_test_result = (test["id"], test_state.detected)
                        phase = single_test_return_to
                        phase_start = now
                        single_test_return_to = None
                        continue
                    test_idx += 1
                    if test_idx >= len(TESTS):
                        # If the user can talk and ConvAI is configured, jump
                        # straight into a natural-language setup conversation.
                        # Otherwise fall back to dwell/keyboard summary.
                        initial_bindings = profile_mod.bindings_from_capabilities(capabilities)
                        voice_pipeline_enabled = bool(capabilities.get("voice"))
                        candidate = SetupAgent(
                            capabilities=capabilities,
                            initial_bindings=initial_bindings,
                            voice_enabled=voice_pipeline_enabled,
                        )
                        if capabilities.get("voice") and candidate.available:
                            # Silence narrator so the agent's first_message isn't talked over.
                            narrator.stop()
                            agent = candidate
                            if agent.start():
                                agent_bindings_snapshot = list(agent.draft.bindings)
                                agent_voice_snapshot = agent.draft.voice_enabled
                                phase = "converse"
                                phase_start = now
                            else:
                                agent = None
                                narrator = Narrator()
                                narrator.start()
                                phase = "summary"
                                phase_start = now
                                confirm_start = 0.0
                                redo_start = 0.0
                                narrator.say(
                                    "Here is what I found. Press Enter or hover the"
                                    " right button if it looks good."
                                )
                        else:
                            phase = "summary"
                            phase_start = now
                            confirm_start = 0.0
                            redo_start = 0.0
                            narrator.say(
                                "Here is what I found. Press Enter or hover the"
                                " right button if it looks good."
                            )
                    else:
                        test_state = TestState(TESTS[test_idx]["id"], now)
                        narrator.say(TEST_SPOKEN[TESTS[test_idx]["id"]])

            elif phase == "converse":
                assert agent is not None
                _draw_converse(display, agent, now - phase_start)

                # Publish live signal snapshot so what_can_i_see() can answer.
                agent.draft.live_signals = _read_live_signals(
                    face_res.multi_face_landmarks,
                    hand_res.multi_hand_landmarks,
                )

                # Agent asked to re-run a single test?
                if agent.draft.pending_test:
                    target = agent.draft.pending_test
                    agent.draft.pending_test = None
                    try:
                        idx = next(i for i, t in enumerate(TESTS) if t["id"] == target)
                    except StopIteration:
                        idx = None
                    if idx is not None:
                        test_idx = idx
                        test_state = TestState(TESTS[idx]["id"], now)
                        single_test_return_to = "converse"
                        phase = "test"
                        continue

                # Agent asked to open the exploration view?
                if agent.draft.pending_explore:
                    agent.draft.pending_explore = False
                    explore_start = now
                    phase = "explore"
                    phase_start = now
                    continue

                # ESC during conversation -> accept whatever the agent has
                # collected and save. Users often say "save it" aloud then
                # hit Esc to finalize; previously that dropped all abilities
                # gathered during the conversation.
                if key == 27:
                    agent.draft.finished = True
                    agent.end()
                    continue

                if agent.draft.redo_requested:
                    agent.end()
                    agent = None
                    capabilities = {cid: False for cid in profile_mod.CAPABILITY_IDS}
                    test_idx = 0
                    test_state = TestState(TESTS[0]["id"], now)
                    phase = "test"
                    narrator = Narrator()
                    narrator.start()
                    narrator.say(TEST_SPOKEN[TESTS[0]["id"]])
                    continue

                if agent.is_finished():
                    # Build the profile from the agent's final draft.
                    result_profile = profile_mod.from_capabilities(capabilities)
                    result_profile["bindings"] = agent.draft.bindings
                    result_profile["voice_enabled"] = agent.draft.voice_enabled
                    # Merge in the agent-confirmed user abilities (fall back to
                    # capability-based guesses if the agent didn't ask).
                    abilities = result_profile.get("user_abilities", {})
                    ability_fields = (
                        "can_see", "can_hear", "can_speak",
                        "can_use_hands", "can_type",
                    )
                    for f in ability_fields:
                        v = getattr(agent.draft, f, None)
                        if v is not None:
                            abilities[f] = bool(v)
                    abilities["confirmed"] = agent.draft.abilities_confirmed
                    result_profile["user_abilities"] = abilities
                    # Derive runtime prefs from abilities (deaf -> captions,
                    # blind -> narration, mute+no-keyboard -> on-screen kb).
                    prefs = profile_mod.apply_ability_preferences(
                        result_profile.get("preferences", {}), abilities,
                    )
                    result_profile["preferences"] = prefs
                    profile_mod.save(result_profile)
                    print(f"onboarding: profile saved -> {profile_mod.PROFILE_PATH}", flush=True)
                    agent = None
                    narrator = Narrator()
                    narrator.start()
                    phase = "done"
                    phase_start = now

            elif phase == "explore":
                signals = _read_live_signals(
                    face_res.multi_face_landmarks,
                    hand_res.multi_hand_landmarks,
                )
                # Keep the agent's live-signals dict fresh while exploring.
                if agent is not None:
                    agent.draft.live_signals = signals

                _draw_explore(display, signals, now - explore_start)

                # Exit on Esc or if the agent ended (e.g. user said "done" and
                # agent called no more tools) -- actually the agent stays alive
                # during exploration. Exit on Esc only, or after 45s timeout.
                if key == 27 or (now - explore_start) > 45:
                    phase = "converse" if agent is not None else "summary"
                    phase_start = now

            elif phase == "summary":
                proposed = profile_mod.bindings_from_capabilities(capabilities)

                # Confirm / redo via dwell or keys.
                # Confirm zone: right 40% of screen. Redo zone: left 40%.
                confirm_hovering = False
                redo_hovering = False
                if cursor_xy is not None:
                    if cursor_xy[0] > DISPLAY_W * 0.6 and cursor_xy[1] > DISPLAY_H * 0.55:
                        confirm_hovering = True
                    elif cursor_xy[0] < DISPLAY_W * 0.4 and cursor_xy[1] > DISPLAY_H * 0.55:
                        redo_hovering = True

                if confirm_hovering and confirm_start == 0.0:
                    confirm_start = now
                elif not confirm_hovering:
                    confirm_start = 0.0
                if redo_hovering and redo_start == 0.0:
                    redo_start = now
                elif not redo_hovering:
                    redo_start = 0.0

                conf_prog = 0.0 if confirm_start == 0.0 else min(1.0, (now - confirm_start) / 1.5)
                redo_prog = 0.0 if redo_start == 0.0 else min(1.0, (now - redo_start) / 1.5)

                _draw_summary(display, capabilities, proposed, conf_prog, redo_prog)

                confirm_key = key in (13, 10)  # Enter
                redo_key = key in (ord("r"), ord("R"))

                if confirm_key or conf_prog >= 1.0:
                    result_profile = profile_mod.from_capabilities(capabilities)
                    profile_mod.save(result_profile)
                    print(f"onboarding: profile saved -> {profile_mod.PROFILE_PATH}", flush=True)
                    narrator.say("Great. Ember is ready.")
                    phase = "done"
                    phase_start = now

                elif redo_key or redo_prog >= 1.0:
                    # Reset everything and run tests again.
                    capabilities = {cid: False for cid in profile_mod.CAPABILITY_IDS}
                    test_idx = 0
                    test_state = TestState(TESTS[0]["id"], now)
                    phase = "test"
                    narrator.say(TEST_SPOKEN[TESTS[0]["id"]])

            elif phase == "done":
                _draw_wordmark(display, 60, 46)
                # Success circle
                cx, cy = DISPLAY_W // 2, 300
                alpha = min(1.0, (now - phase_start) / 0.5)
                for r, col, a in [(82, ACCENT_OK_D, 0.25 * alpha),
                                  (62, ACCENT_OK, 0.55 * alpha)]:
                    overlay = display.copy()
                    cv2.circle(overlay, (cx, cy), r, col, -1, cv2.LINE_AA)
                    cv2.addWeighted(overlay, a, display, 1 - a, 0, display)
                cv2.circle(display, (cx, cy), 42, ACCENT_OK, -1, cv2.LINE_AA)
                # Checkmark
                cv2.line(display, (cx - 18, cy + 2), (cx - 4, cy + 16),
                         TEXT_PRIMARY, 4, cv2.LINE_AA)
                cv2.line(display, (cx - 4, cy + 16), (cx + 20, cy - 14),
                         TEXT_PRIMARY, 4, cv2.LINE_AA)

                _put_center(display, "You're set", 430, 1.6, TEXT_PRIMARY, 1)
                _put_center(display, "Ember is starting up...", 475, 0.65,
                            TEXT_SECONDARY, 1, font=FONT_LIGHT)
                if (now - phase_start) > DONE_FLASH_S:
                    break

            # Draw cursor on top, only when head is capable (so we don't mock
            # users who can't use head tracking).
            if cursor_xy is not None and phase in ("summary", "done"):
                # Halo + dot
                overlay = display.copy()
                cv2.circle(overlay, cursor_xy, 22, ACCENT_EMBER, -1, cv2.LINE_AA)
                cv2.addWeighted(overlay, 0.25, display, 0.75, 0, display)
                cv2.circle(display, cursor_xy, 12, ACCENT_EMBER, 2, cv2.LINE_AA)
                cv2.circle(display, cursor_xy, 4, ACCENT_EMBER, -1, cv2.LINE_AA)

            cv2.imshow(WIN, display)
    finally:
        try:
            if agent is not None:
                agent.end()
        except Exception:
            pass
        try:
            narrator.stop()
        except Exception:
            pass
        mic.stop()
        cap.release()
        cv2.destroyWindow(WIN)
        try:
            face.close()
            hands.close()
        except Exception:
            pass

    return result_profile
