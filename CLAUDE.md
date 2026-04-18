# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Pre-code. Repo contains only `README.md` and `vision.md`. No package manifests, no build/test/lint commands exist yet — do not invent them. When scaffolding, create the structure described below rather than asking the user what to pick.

The repo is named `ember` but the product is **Axis** — a webcam-only accessibility input layer for the Hesburgh Hackathon 2026 (42-hour build, team of 4, Notre Dame). The full brief is in `vision.md`; read it before making architectural decisions.

## Architecture (locked by vision.md)

Axis is three systems in sequence. Keep them as separable processes/modules — do not collapse them into one codebase layer:

1. **Movement Detector** (Python + MediaPipe) — runs face mesh (468 pts) + hand landmarks (21/hand) + pose (33 pts) simultaneously at 30fps on CPU. Runs a 90-second to 2-minute signal-variance analysis on every landmark to *automatically discover* which body parts the user can control reliably. This auto-discovery is the novel contribution; manual setup flows defeat the entire project.
2. **Mapping Layer** (React frontend ↔ Python local server over WebSocket) — user drags discovered motions onto action slots (mouse direction, dwell-click, keyboard keys, macros). Dwell-to-click threshold is 600ms. Proportional cursor speed from head-tilt angle.
3. **System Driver** (OS-level virtual input device) — Linux `uinput` for the demo, Windows `vJoy + SendInput`, macOS `CGEvent tap`. The OS must see Axis as a real keyboard + mouse so every existing app (including games reading raw HID) works unmodified. **Do not build an in-app-only input layer** — that is exactly what every failed competitor did (Camera Mouse, Enable Viacam, GazePointer).

Demo machine is Arch Linux for native `uinput`. Only the Linux path needs to ship in 42 hours.

## MVP Scope (demo-critical, in order)

1. MediaPipe face mesh + pose live from webcam at stable 30fps
2. Variance analysis identifying 4–6 candidate controls during 90-second calibration
3. Calibration UI with live video overlay showing detected zones highlighted
4. Drag-to-map interface, 4 action slots
5. Head tilt → smooth proportional mouse cursor
6. 600ms dwell → left click
7. 2 facial gestures → 2 configurable keyboard keys
8. `uinput` virtual device emitting to OS
9. Works in Chrome + one web-based game

Out of scope for the hackathon (roadmap only, do not build): scanning mode, action wheel, Windows/Mac drivers, multi-profile save, cloud sync, additional gesture types beyond the two required.

## Stack Decisions (already made — do not re-litigate)

- **CV**: MediaPipe Python (face mesh + pose + hands). CPU only, no GPU assumed.
- **App server**: Python with FastAPI or Flask serving a local WebSocket to the frontend.
- **Virtual input**: `uinput` via Python `ctypes` or `python-evdev` on Linux. Package for demo machine.
- **Frontend**: React + WebSocket client. Real-time overlay on live video.
- **Package manager** (when JS is added): `pnpm`, not npm.

These override the global default preferences for this repo — Python is mandatory for the CV + driver layers because MediaPipe and `uinput` both live there.

## Working Rules Specific to This Project

- **Latency is the product.** Every feature decision trades off against the CV→driver loop staying under ~33ms end-to-end. If something adds perceptible lag, it does not ship.
- **Variance-analysis auto-discovery is the differentiator.** Do not replace it with a manual "pick your gesture" flow under time pressure — that collapses the project into an existing competitor.
- **The driver output is what makes this real.** If you are tempted to ship a version that only controls a built-in Axis UI (skipping `uinput`), stop and escalate to the user. That version is a demo competitors have already shipped.
- **Demo-first development**: the hour-by-hour timeline in `vision.md` (lines 213–222) is the source of truth for what to build when. Prefer making the demo path bulletproof over breadth.
