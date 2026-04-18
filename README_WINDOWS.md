# ember — Windows setup

Windows-specific setup for the Axis skeleton preview. For Linux setup, project overview, and controls, see `README.md`.

## What works on Windows

- Camera preview at 30fps
- Full-body skeleton (pose landmarks)
- Face mesh (hundreds of landmarks tracking your face)
- Hand landmarks (21 per hand)
- Mouth-open detection (visible on screen)
- Finger-tip tracking (yellow circle on your index finger)

## What does NOT work on Windows (yet)

- **Virtual cursor control** — the `uinput` backend is Linux-kernel-only. On Windows the script runs in preview-only mode: detection works, but the OS cursor does not move and mouth-open does not fire real clicks.

Cross-platform cursor support is on the roadmap but not in this branch.

---

## Prerequisites

- **Windows 10/11**
- **PowerShell** (default on both)
- A **working webcam** (built-in laptop cam or USB)
- **~1 GB free disk** (Python + MediaPipe wheels are chunky)

No need to pre-install Python — `uv` will handle that.

---

## 1. Install `uv` (one-time, per machine)

Open **PowerShell** and paste:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then **close and reopen PowerShell** so `uv` is on your `PATH`. Verify:

```powershell
uv --version
```

If `uv` is still not recognized, sign out of Windows and back in.

---

## 2. Clone the repo and switch to this branch

```powershell
git clone https://github.com/Matusvec/ember.git
cd ember
git checkout matus
```

---

## 3. Create the virtualenv and install dependencies

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe "mediapipe==0.10.14" opencv-python
```

**Do not install `evdev`.** It is a Linux-only package and will fail to build on Windows with compiler errors. The code's `cursor.py` handles its absence gracefully — the script runs fine without it, just without cursor control.

---

## 4. Grant webcam permission

Windows Settings → **Privacy & Security → Camera**:

- Enable **"Camera access"** (top toggle)
- Enable **"Let apps access your camera"**
- Enable **"Let desktop apps access your camera"** (this is the one most commonly missed — without it the webcam opens but returns blank frames)

---

## 5. Run

```powershell
.venv\Scripts\python.exe cv\skeleton_preview.py --os windows
```

Or, if the venv is activated (`.venv\Scripts\Activate.ps1`):

```powershell
python cv\skeleton_preview.py --os windows
```

You should see a window titled **"Axis - skeleton preview"** showing your webcam feed with:

- Pose skeleton lines on your torso, shoulders, arms
- Dense face mesh triangles
- Hand landmarks when a hand is visible (yellow circle on index fingertip)
- Top-left: FPS counter, status text, key bindings

Press **`q`** in the window to quit.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `uv` command not found after install | Close PowerShell and reopen it. If still broken, sign out of Windows and back in. |
| Webcam opens but the window is all black | Grant "Let desktop apps access your camera" in Windows Settings → Privacy → Camera. |
| `could not open webcam` | Close any other app using the camera (Zoom, Teams, Skype, browser tab). Only one process can open a Windows webcam at a time. |
| MediaPipe install fails with DLL / C++ runtime errors | Install the latest Microsoft Visual C++ Redistributable from microsoft.com and retry. |
| Window too small, Qt toolbar takes up half the space | Drag the window edge to resize — it is resizable. |
| FPS low (below 15) | Close other GPU-heavy apps. Webcam and MediaPipe share the CPU/GPU. |
| Import error on `evdev` | You installed `evdev` — uninstall it: `uv pip uninstall evdev`. It is Linux-only. |

---

## Notes for the team

On this Windows box you can develop and test all CV logic (landmark detection, variance analysis, gesture classifiers, calibration flow, detection overlays) at full speed. The bit you cannot test here is the final `uinput` → OS cursor leg. That leg is owned by the Linux user. When you push code that emits gesture events or normalized cursor deltas, their Linux machine will consume them and drive the real cursor.

In other words: Windows is the CV + UX dev environment. Linux is the OS-integration dev environment. Both are needed for the full demo.
