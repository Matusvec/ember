"""Per-frame signal extractors.

Pure functions that turn raw MediaPipe results into named signals the mapping
dispatcher consumes. Each returns None if the signal isn't available this frame.

All positions returned as normalized frame coordinates in [0, 1].
"""

from __future__ import annotations

# MediaPipe face mesh landmark indices.
NOSE_TIP = 1           # tip of the nose, works well as a head-position proxy
UPPER_LIP = 13
LOWER_LIP = 14
FOREHEAD = 10
CHIN = 152

# Left eye (user's left, i.e. screen-right in mirrored preview).
LEFT_EYE_OUTER = 33
LEFT_EYE_INNER = 133
LEFT_EYE_TOP = 159
LEFT_EYE_BOTTOM = 145

# Right eye.
RIGHT_EYE_OUTER = 263
RIGHT_EYE_INNER = 362
RIGHT_EYE_TOP = 386
RIGHT_EYE_BOTTOM = 374

# Eyebrow tops (center of each brow — moves vertically when raised).
LEFT_BROW_TOP = 105
RIGHT_BROW_TOP = 334

# MediaPipe hands landmark indices.
INDEX_TIP = 8


def nose_tip(face_landmarks) -> tuple[float, float] | None:
    """Normalized (x, y) of the nose tip. Proxy for head position."""
    if face_landmarks is None:
        return None
    lms = face_landmarks[0].landmark
    return (lms[NOSE_TIP].x, lms[NOSE_TIP].y)


def index_tip(hand_landmarks) -> tuple[float, float] | None:
    """Normalized (x, y) of the first detected hand's index fingertip."""
    if hand_landmarks is None:
        return None
    tip = hand_landmarks[0].landmark[INDEX_TIP]
    return (tip.x, tip.y)


def mouth_ratio(face_landmarks) -> float | None:
    """Mouth opening as a fraction of face height. ~0.08+ means noticeably open."""
    if face_landmarks is None:
        return None
    lms = face_landmarks[0].landmark
    gap = abs(lms[LOWER_LIP].y - lms[UPPER_LIP].y)
    face_h = abs(lms[CHIN].y - lms[FOREHEAD].y)
    if face_h <= 1e-6:
        return None
    return gap / face_h


def eyebrow_raise(face_landmarks) -> float | None:
    """Eyebrow raise as a fraction of face height.

    Measures vertical gap between each eyebrow top and the corresponding eye top,
    averaged across both sides, then normalized by face height. Neutral ~0.04,
    clearly raised ~0.08+. Threshold around 0.06 for "raised" detection.
    """
    if face_landmarks is None:
        return None
    lms = face_landmarks[0].landmark
    face_h = abs(lms[CHIN].y - lms[FOREHEAD].y)
    if face_h <= 1e-6:
        return None
    left_gap = abs(lms[LEFT_EYE_TOP].y - lms[LEFT_BROW_TOP].y)
    right_gap = abs(lms[RIGHT_EYE_TOP].y - lms[RIGHT_BROW_TOP].y)
    return ((left_gap + right_gap) / 2.0) / face_h


def eye_aspect_ratio(face_landmarks, eye: str = "both") -> float | None:
    """Eye aspect ratio — vertical opening / horizontal width.

    Open eyes ~0.3, closed ~0.08. Threshold around 0.18 for "closed" detection.
    eye: "left", "right", or "both" (average).
    """
    if face_landmarks is None:
        return None
    lms = face_landmarks[0].landmark

    def one(top, bot, outer, inner) -> float:
        vert = abs(lms[top].y - lms[bot].y)
        horiz = abs(lms[outer].x - lms[inner].x)
        return vert / horiz if horiz > 1e-6 else 0.0

    left = one(LEFT_EYE_TOP, LEFT_EYE_BOTTOM, LEFT_EYE_OUTER, LEFT_EYE_INNER)
    right = one(RIGHT_EYE_TOP, RIGHT_EYE_BOTTOM, RIGHT_EYE_OUTER, RIGHT_EYE_INNER)

    if eye == "left":
        return left
    if eye == "right":
        return right
    return (left + right) / 2.0
