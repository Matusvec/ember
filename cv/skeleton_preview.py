"""Live webcam preview with MediaPipe pose + face mesh + hand landmarks drawn on top.

Run:  python cv/skeleton_preview.py
Quit: press q in the video window

Bindings (which gesture does what) are in mapping.json at the repo root.
Edit that file while this is running — changes are picked up on the next frame.

Latency notes:
  - V4L2 buffers up to 4 frames by default (~130ms at 30fps). We drop buffer to 1.
  - A grabber thread keeps only the latest frame, so the main loop never reads stale data.
  - Pose uses model_complexity=0 (lite). Face mesh skips iris refinement. Hands stay light.
  - Capture is 640x480 — MediaPipe internally works at low res anyway; the display window
    upscales for visibility.
"""

import argparse
import sys
import threading
import time
from pathlib import Path

import cv2
import mediapipe as mp

from cursor import VirtualMouse
from mapping import MappingConfig, MappingDispatcher
from sources import (
    eye_aspect_ratio,
    eyebrow_raise,
    index_tip,
    mouth_ratio,
    nose_tip,
)


def pick_capture_backend(os_name: str) -> int:
    if os_name == "linux":
        return cv2.CAP_V4L2
    if os_name == "windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


mp_pose = mp.solutions.pose
mp_face = mp.solutions.face_mesh
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles

WIN = "Axis - skeleton preview"
CAP_W, CAP_H = 640, 480
DISPLAY_W, DISPLAY_H = 1280, 720

# Relative to the repo root.  Preview is run from repo root, so this resolves.
DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent.parent / "mapping.json"


class LatestFrameGrabber:
    """Background thread that continuously reads the webcam and keeps only the newest frame.

    The V4L2 kernel buffer holds frames in FIFO order; even with BUFFERSIZE=1 the main
    loop can drift a frame behind if it processes slower than the camera produces. This
    grabber always drains to the latest frame, so .read() gives us *now*.
    """

    def __init__(self, cap: cv2.VideoCapture) -> None:
        self.cap = cap
        self.lock = threading.Lock()
        self.frame = None
        self.stopped = False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while not self.stopped:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.001)

    def read(self):
        with self.lock:
            return self.frame

    def stop(self) -> None:
        self.stopped = True
        self.thread.join(timeout=1.0)


def parse_args() -> argparse.Namespace:
    auto_os = "linux" if sys.platform.startswith("linux") else (
        "windows" if sys.platform.startswith("win") else "other"
    )
    ap = argparse.ArgumentParser(description="Axis skeleton preview")
    ap.add_argument(
        "--os",
        choices=["linux", "windows", "auto"],
        default="auto",
        help="Target OS. Chooses webcam backend and whether to enable cursor control. "
        f"'auto' (default) detects at runtime: {auto_os}",
    )
    ap.add_argument(
        "--mapping",
        default=str(DEFAULT_MAPPING_PATH),
        help="Path to mapping.json (default: %(default)s)",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    os_name = args.os if args.os != "auto" else (
        "linux" if sys.platform.startswith("linux") else (
            "windows" if sys.platform.startswith("win") else "other"
        )
    )
    print(f"OS: {os_name} (requested: {args.os})", flush=True)

    backend = pick_capture_backend(os_name)
    cap = cv2.VideoCapture(0, backend)
    if not cap.isOpened():
        raise SystemExit(f"could not open webcam (backend={backend}, os={os_name})")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_H)
    cap.set(cv2.CAP_PROP_FPS, 30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    ok, first = cap.read()
    if not ok:
        raise SystemExit("webcam opened but read failed")
    print(f"camera ok: frame {first.shape[1]}x{first.shape[0]}, mean={first.mean():.1f}", flush=True)

    grabber = LatestFrameGrabber(cap)

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, DISPLAY_W, DISPLAY_H)

    pose = mp_pose.Pose(model_complexity=0, enable_segmentation=False)
    face = mp_face.FaceMesh(max_num_faces=1, refine_landmarks=False)
    hands = mp_hands.Hands(max_num_hands=2, model_complexity=0)

    mouse = None
    dispatcher_enabled = False
    if os_name == "linux":
        try:
            mouse = VirtualMouse()
            dispatcher_enabled = True
            print("virtual mouse ready", flush=True)
        except (PermissionError, RuntimeError) as exc:
            print(f"WARN: cursor control disabled ({exc}). "
                  "Run: sudo chmod 0666 /dev/uinput", flush=True)
    else:
        print(f"cursor control disabled on {os_name} — preview only", flush=True)

    config = MappingConfig(args.mapping)
    dispatcher = MappingDispatcher(config, mouse)

    last = time.monotonic()
    fps_ema = 0.0

    try:
        while True:
            frame = grabber.read()
            if frame is None:
                time.sleep(0.001)
                continue

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False

            pose_res = pose.process(rgb)
            face_res = face.process(rgb)
            hands_res = hands.process(rgb)

            if pose_res.pose_landmarks:
                mp_drawing.draw_landmarks(
                    frame,
                    pose_res.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS,
                    landmark_drawing_spec=mp_styles.get_default_pose_landmarks_style(),
                )

            if face_res.multi_face_landmarks:
                for face_lms in face_res.multi_face_landmarks:
                    mp_drawing.draw_landmarks(
                        frame,
                        face_lms,
                        mp_face.FACEMESH_TESSELATION,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=mp_styles.get_default_face_mesh_tesselation_style(),
                    )
                    mp_drawing.draw_landmarks(
                        frame,
                        face_lms,
                        mp_face.FACEMESH_CONTOURS,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=mp_styles.get_default_face_mesh_contours_style(),
                    )

            if hands_res.multi_hand_landmarks:
                for hand_lms in hands_res.multi_hand_landmarks:
                    mp_drawing.draw_landmarks(
                        frame,
                        hand_lms,
                        mp_hands.HAND_CONNECTIONS,
                        mp_styles.get_default_hand_landmarks_style(),
                        mp_styles.get_default_hand_connections_style(),
                    )

            # Extract source values for the dispatcher.
            sources_dict = {
                "nose": nose_tip(face_res.multi_face_landmarks),
                "index_tip": index_tip(hands_res.multi_hand_landmarks),
                "mouth": mouth_ratio(face_res.multi_face_landmarks),
                "ear": eye_aspect_ratio(face_res.multi_face_landmarks, "both"),
                "brow": eyebrow_raise(face_res.multi_face_landmarks),
            }

            now = time.monotonic()
            config.maybe_reload()
            events = dispatcher.dispatch(sources_dict, now) if dispatcher_enabled else []

            # ── Visual overlays for active signals ────────────────────────────
            h, w = frame.shape[:2]

            if sources_dict["nose"] is not None:
                nx, ny = sources_dict["nose"]
                cv2.circle(frame, (int(nx * w), int(ny * h)), 8, (0, 200, 255), 2)
                cv2.drawMarker(
                    frame, (int(nx * w), int(ny * h)),
                    (0, 200, 255), cv2.MARKER_CROSS, 18, 1,
                )

            if sources_dict["index_tip"] is not None:
                ix, iy = sources_dict["index_tip"]
                cv2.circle(frame, (int(ix * w), int(iy * h)), 12, (0, 255, 255), 2)

            ear = sources_dict["ear"]
            brow = sources_dict["brow"]
            ear_text = f"EAR {ear:.2f}" if ear is not None else "EAR —"
            brow_text = f"BROW {brow:.2f}" if brow is not None else "BROW —"

            blink_fired = any(e.startswith("blink") for e in events)
            brow_fired = any(e.startswith("brow") for e in events)
            mouth_hold = any(e.startswith("mouth") for e in events)

            if blink_fired:
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (255, 100, 0), 6)
                cv2.putText(
                    frame, "BLINK CLICK", (12, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 0), 2, cv2.LINE_AA,
                )
            if brow_fired:
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 255, 255), 6)
                cv2.putText(
                    frame, "BROW CLICK", (12, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA,
                )
            if mouth_hold:
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 6)
                cv2.putText(
                    frame, "MOUTH HOLD", (12, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA,
                )

            inst_fps = 1.0 / max(now - last, 1e-6)
            last = now
            fps_ema = inst_fps if fps_ema == 0.0 else 0.9 * fps_ema + 0.1 * inst_fps

            enabled_count = sum(1 for b in config.bindings if b.enabled)
            disp_state = "ON" if (mouse and dispatcher_enabled) else "OFF"
            cv2.putText(
                frame,
                f"{fps_ema:5.1f} fps   dispatcher {disp_state}   "
                f"{enabled_count} bindings   {ear_text}   {brow_text}   [d] toggle  [q] quit",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow(WIN, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("d") and mouse is not None:
                dispatcher_enabled = not dispatcher_enabled
                if not dispatcher_enabled:
                    # release any held buttons cleanly
                    for btn in ("left", "right", "middle"):
                        try:
                            mouse.release(btn)
                        except Exception:
                            pass
    finally:
        grabber.stop()
        cap.release()
        cv2.destroyAllWindows()
        if mouse is not None:
            mouse.close()


if __name__ == "__main__":
    main()
