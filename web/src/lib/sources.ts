// Ports of cv/sources.py: pure-function signal extractors against
// @mediapipe/tasks-vision FaceLandmarker + HandLandmarker outputs.
//
// All inputs are the `normalizedLandmarks` arrays — each landmark is { x, y, z }
// in 0..1 frame coords. Returns null when a signal isn't available this frame.

import type { NormalizedLandmark } from "@mediapipe/tasks-vision";

// Face mesh landmark indices (same as Python source).
export const IDX = {
  NOSE_TIP: 1,
  UPPER_LIP: 13,
  LOWER_LIP: 14,
  FOREHEAD: 10,
  CHIN: 152,
  LEFT_EYE_OUTER: 33,
  LEFT_EYE_INNER: 133,
  LEFT_EYE_TOP: 159,
  LEFT_EYE_BOTTOM: 145,
  RIGHT_EYE_OUTER: 263,
  RIGHT_EYE_INNER: 362,
  RIGHT_EYE_TOP: 386,
  RIGHT_EYE_BOTTOM: 374,
  LEFT_BROW_TOP: 105,
  RIGHT_BROW_TOP: 334,
  INDEX_TIP: 8,
};

function faceH(lms: NormalizedLandmark[]): number {
  return Math.abs(lms[IDX.CHIN].y - lms[IDX.FOREHEAD].y);
}

export function noseTip(faces: NormalizedLandmark[][] | undefined):
    [number, number] | null {
  if (!faces || faces.length === 0) return null;
  const l = faces[0][IDX.NOSE_TIP];
  return [l.x, l.y];
}

export function indexTip(hands: NormalizedLandmark[][] | undefined):
    [number, number] | null {
  if (!hands || hands.length === 0) return null;
  const l = hands[0][IDX.INDEX_TIP];
  return [l.x, l.y];
}

export function mouthRatio(faces: NormalizedLandmark[][] | undefined): number | null {
  if (!faces || faces.length === 0) return null;
  const lms = faces[0];
  const gap = Math.abs(lms[IDX.LOWER_LIP].y - lms[IDX.UPPER_LIP].y);
  const h = faceH(lms);
  return h <= 1e-6 ? null : gap / h;
}

export function eyebrowRaise(faces: NormalizedLandmark[][] | undefined): number | null {
  if (!faces || faces.length === 0) return null;
  const lms = faces[0];
  const h = faceH(lms);
  if (h <= 1e-6) return null;
  const left  = Math.abs(lms[IDX.LEFT_EYE_TOP].y  - lms[IDX.LEFT_BROW_TOP].y);
  const right = Math.abs(lms[IDX.RIGHT_EYE_TOP].y - lms[IDX.RIGHT_BROW_TOP].y);
  return ((left + right) / 2.0) / h;
}

export function eyeAspectRatio(faces: NormalizedLandmark[][] | undefined,
                               eye: "left" | "right" | "both" = "both"): number | null {
  if (!faces || faces.length === 0) return null;
  const lms = faces[0];
  const one = (top: number, bot: number, outer: number, inner: number) => {
    const vert  = Math.abs(lms[top].y - lms[bot].y);
    const horiz = Math.abs(lms[outer].x - lms[inner].x);
    return horiz > 1e-6 ? vert / horiz : 0;
  };
  const left  = one(IDX.LEFT_EYE_TOP,  IDX.LEFT_EYE_BOTTOM,  IDX.LEFT_EYE_OUTER,  IDX.LEFT_EYE_INNER);
  const right = one(IDX.RIGHT_EYE_TOP, IDX.RIGHT_EYE_BOTTOM, IDX.RIGHT_EYE_OUTER, IDX.RIGHT_EYE_INNER);
  if (eye === "left")  return left;
  if (eye === "right") return right;
  return (left + right) / 2;
}
