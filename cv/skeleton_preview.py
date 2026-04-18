"""Live webcam preview with MediaPipe pose + face mesh + hand landmarks drawn on top.

Run:  python cv/skeleton_preview.py
Quit: press q in the video window

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

import cv2
import mediapipe as mp

from cursor import VirtualMouse


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

CURSOR_SENSITIVITY = 2500
CURSOR_SMOOTHING = 0.4
INDEX_TIP = 8

UPPER_LIP = 13
LOWER_LIP = 14
FOREHEAD = 10
CHIN = 152
MOUTH_OPEN_THRESHOLD = 0.08
CLICK_COOLDOWN_S = 0.5


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
    cursor_on = False
    if os_name == "linux":
        try:
            mouse = VirtualMouse()
            cursor_on = True
            print("virtual mouse ready — point your index finger to move the cursor", flush=True)
        except (PermissionError, RuntimeError) as exc:
            print(f"WARN: cursor control disabled ({exc}). "
                  "Run: sudo chmod 0666 /dev/uinput", flush=True)
    else:
        print(f"cursor control disabled on {os_name} — preview only", flush=True)

    prev_finger = None
    smoothed_dx = 0.0
    smoothed_dy = 0.0
    mouth_was_open = False
    last_click_t = 0.0
    click_flash_until = 0.0
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

            mouth_ratio = 0.0
            mouth_is_open = False
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
                lms = face_res.multi_face_landmarks[0].landmark
                mouth_gap = abs(lms[LOWER_LIP].y - lms[UPPER_LIP].y)
                face_h = abs(lms[CHIN].y - lms[FOREHEAD].y)
                mouth_ratio = mouth_gap / face_h if face_h > 1e-6 else 0.0
                mouth_is_open = mouth_ratio > MOUTH_OPEN_THRESHOLD

            index_tip = None
            if hands_res.multi_hand_landmarks:
                for hand_lms in hands_res.multi_hand_landmarks:
                    mp_drawing.draw_landmarks(
                        frame,
                        hand_lms,
                        mp_hands.HAND_CONNECTIONS,
                        mp_styles.get_default_hand_landmarks_style(),
                        mp_styles.get_default_hand_connections_style(),
                    )
                tip = hands_res.multi_hand_landmarks[0].landmark[INDEX_TIP]
                index_tip = (tip.x, tip.y)
                h, w = frame.shape[:2]
                cv2.circle(frame, (int(tip.x * w), int(tip.y * h)), 12, (0, 255, 255), 2)

            if mouse is not None and cursor_on and index_tip is not None:
                if prev_finger is not None:
                    raw_dx = (index_tip[0] - prev_finger[0]) * CURSOR_SENSITIVITY
                    raw_dy = (index_tip[1] - prev_finger[1]) * CURSOR_SENSITIVITY
                    smoothed_dx = CURSOR_SMOOTHING * raw_dx + (1 - CURSOR_SMOOTHING) * smoothed_dx
                    smoothed_dy = CURSOR_SMOOTHING * raw_dy + (1 - CURSOR_SMOOTHING) * smoothed_dy
                    mouse.move(int(smoothed_dx), int(smoothed_dy))
                prev_finger = index_tip
            else:
                prev_finger = None
                smoothed_dx = smoothed_dy = 0.0

            now = time.monotonic()
            if mouse is not None and cursor_on:
                if mouth_is_open and not mouth_was_open:
                    mouse.press("left")
                elif not mouth_is_open and mouth_was_open:
                    mouse.release("left")
            elif mouse is not None and not cursor_on and mouth_was_open:
                mouse.release("left")
            mouth_was_open = mouth_is_open

            if mouth_is_open and mouse is not None and cursor_on:
                h, w = frame.shape[:2]
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), (0, 0, 255), 8)
                cv2.putText(
                    frame, "HOLDING CLICK", (12, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA,
                )

            inst_fps = 1.0 / max(now - last, 1e-6)
            last = now
            fps_ema = inst_fps if fps_ema == 0.0 else 0.9 * fps_ema + 0.1 * inst_fps
            status = "cursor ON" if (mouse and cursor_on) else "cursor OFF"
            cv2.putText(
                frame,
                f"{fps_ema:5.1f} fps   {status}   [c] toggle  [q] quit",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow(WIN, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("c") and mouse is not None:
                cursor_on = not cursor_on
                prev_finger = None
    finally:
        grabber.stop()
        cap.release()
        cv2.destroyAllWindows()
        if mouse is not None:
            mouse.close()


if __name__ == "__main__":
    main()
