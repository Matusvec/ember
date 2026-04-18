# ember — Axis prototype

Webcam-driven accessibility input layer. Live skeleton preview with MediaPipe, finger-tracked cursor, mouth-open for click-and-hold.

Full vision: see `vision.md`.
Windows setup: see `README_WINDOWS.md`.

## What works on which OS

| OS | Camera preview + landmarks | Virtual cursor + click |
|---|:---:|:---:|
| Linux | yes | yes (via `uinput`) |
| Windows | yes | **no** — preview-only |
| macOS | yes (with camera permission granted) | **no** — preview-only |

Cursor control currently uses Linux `uinput`. On Windows/macOS the script detects the OS and runs in preview-only mode (skeleton + mouth detection visible, just no OS cursor movement).

---

## Linux setup (Arch / Ubuntu)

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Get the code
git clone https://github.com/Matusvec/ember.git
cd ember
git checkout matus

# venv + deps (include evdev for cursor control)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "mediapipe==0.10.14" opencv-python evdev

# One-time per boot: grant uinput write access
sudo chmod 0666 /dev/uinput

# Run
.venv/bin/python cv/skeleton_preview.py
```

For a permanent uinput fix (survives reboot):

```bash
sudo usermod -a -G input $USER
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
# then LOG OUT and back in
```

---

## Controls

| Input | Action |
|---|---|
| Move **index fingertip** (yellow circle) | moves cursor (Linux only) |
| **Open mouth** noticeably | holds down left click — close mouth to release (Linux only) |
| Press **`c`** in window | toggle cursor control on/off |
| Press **`q`** in window | quit |

---

## CLI flags

```
python cv/skeleton_preview.py --os {linux,windows,auto}
```

- `--os auto` (default) — detects the OS at runtime and picks the right webcam backend
- `--os linux` — forces V4L2 backend + enables `uinput` cursor control
- `--os windows` — forces DirectShow backend + disables cursor control
