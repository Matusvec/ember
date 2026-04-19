# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Repo is `ember`; product is **Axis** — a webcam-only accessibility input layer built for the Hesburgh Hackathon 2026 (Notre Dame, team of 4, 42-hour build). Full brief in `vision.md`. Demo target is Arch Linux because `uinput` is native; Windows/macOS run in preview-only mode today (see `README_WINDOWS.md`).

## Run commands

Python env is created with `uv` into `.venv/` (Python 3.12). There is **no requirements.txt / pyproject.toml**. Install deps explicitly with `uv pip install --python .venv/bin/python mediapipe==0.10.14 opencv-python evdev fastapi uvicorn python-dotenv pydub sounddevice numpy` and whatever else gets imported; update this list if a new top-level import is added to `axis.py`, `server/main.py`, `voice/`, or `tools/actions.py`.

One-time per boot on Linux: `sudo chmod 0666 /dev/uinput` (permanent fix documented in `README.md`).

| Task | Command |
|---|---|
| Run the full app (CV + optional voice, with onboarding on first launch) | `.venv/bin/python axis.py` |
| Skip onboarding / force re-onboard | `python axis.py --no-onboard` / `python axis.py --onboard` |
| Enable voice pipeline | `python axis.py --voice` (needs `ELEVENLABS_API_KEY` + `ELEVENLABS_AGENT_ID` in `.env`) |
| Headless / picture-in-picture preview | `python axis.py --no-preview` or `--pip` |
| Raw CV preview only (older entry point, no onboarding/voice) | `python cv/skeleton_preview.py` |
| FastAPI server for the browser UI | `python -m server` or `uvicorn server.main:app --reload` (binds `127.0.0.1:8000`) |
| Web dev server | `cd web && pnpm install && pnpm dev` (Vite on `:5173`, CORS allowlisted) |
| Web production build | `cd web && pnpm build` (output in `web/dist/`, served by FastAPI when present) |
| Web typecheck | `cd web && pnpm typecheck` |
| Install/uninstall Linux autostart | `python axis.py --install-autostart` / `--uninstall-autostart` |
| Sync local `TOOL_SCHEMAS` to ElevenLabs workspace + agent | `python -m tools.sync_agent_tools` (add `--dry-run` to preview) |

There is no test suite, linter, or formatter wired up. Do not invent one unless asked.

## Architecture

Three independent subsystems. Keep them separable — collapsing them defeats the design.

### 1. CV pipeline (`cv/`, entered via `axis.py` → `cv/skeleton_preview.py`)

- `skeleton_preview.py` owns the 30 fps capture loop. It uses a `LatestFrameGrabber` thread + `CAP_PROP_BUFFERSIZE=1` to always process *now* — this is deliberate, latency is the product.
- `sources.py` extracts per-frame scalar/vector signals (`nose`, `index_tip`, `mouth`, `ear`, `brow`) from MediaPipe face mesh + pose + hands.
- `templates.py` + `recorder.py` implement user-recorded gesture templates (press `r` in the preview window). Matched gestures appear in the source dict as `gesture:<name>`.
- `mapping.py` is the dispatcher: reads `mapping.json` (hot-reloaded via mtime), iterates bindings, and calls into the virtual mouse. New source types and actions are added here.
- `cursor.py` is the Linux-only `VirtualMouse`: wraps `evdev.UInput` to emit relative mouse motion, button presses, scroll wheel, **and ASCII keyboard events** (`VirtualMouse.type(text)` — used by the voice tools). Non-Linux construction raises `RuntimeError`; callers fall back to preview-only.
- `filters.py` is a One-Euro filter used to smooth cursor deltas.
- `onboarding.py` + `setup_agent.py` run a 14s-per-test wizard in a native OpenCV window that detects capabilities, then writes `~/.ember/profile.json`. The browser flow under `web/src/pages/` is the newer alternative to this wizard.

### 2. Profile + mapping (`cv/profile.py`, `contracts/`)

- Source of truth is `~/.ember/profile.json` (schema: `contracts/profile.schema.json`, plus the v2/v3 shape in `cv/profile.py`). Repo-local `mapping.json` is a legacy fallback only used when no profile exists.
- `profile.py` derives **both** bindings and an `interaction_mode` (`full` / `voice_first` / `visual_only` / `motor_limited`) from raw capability booleans. The mode decides runtime behavior (auto-wake voice, TTS, narration). Logic lives in `infer_mode` and `mode_preferences`. If you change heuristics, bump the profile `version` and handle old versions — existing users have files on disk.
- `user_abilities` (can_see/can_hear/can_speak/can_type) is self-reported via the setup agent; it refines — but does not override — capability-based inference.

### 3. Voice pipeline (`voice/`, `tools/`, `tts/`) — opt-in, runs on its own asyncio loop

- `axis.py` starts `voice.bridge.VoiceBridge` on a dedicated thread with its own event loop when `--voice` (or `profile.voice_enabled`) is set. **Never** put voice coroutines on the CV loop.
- Wake word → `voice/wake.py` (Picovoice Porcupine, keyword configurable via `AXIS_WAKE_KEYWORD`). Session → `voice/conversation.py` (ElevenLabs Conversational AI websocket). Session end → back to wake-listening.
- `EMBER_VOICE_AUTO_WAKE=1` (set automatically for voice-first users in `axis.py`) opens the ConvAI session on startup and auto-restarts it so the user never needs a trigger.
- `tools/actions.py` exposes `ActionDispatcher` — **the single shared boundary** between CV and voice. Both layers call its methods; only it talks to `VirtualMouse` (or `pyautogui` as fallback). Tool schemas exported to ElevenLabs live in `TOOL_SCHEMAS`; if you add a tool, update the schema **and** the handler dict in `get_client_tools()` so both sides stay in sync. After changing `TOOL_SCHEMAS`, run `python -m tools.sync_agent_tools` so the ElevenLabs workspace has a persistent tool record with matching `tool_ids` attached to the agent — otherwise only the per-session conversation override carries the schema and things break if the override path changes.
- `voice/conversation.py` fetches existing agent `tool_ids` at session start and echoes them back in the prompt override so starting a session does not wipe the agent's attached tools. Keep this behavior — ElevenLabs silently clears unreferenced tool ids.
- `cv/half_duplex_audio.py` is the default `audio_interface` passed to the ElevenLabs `Conversation`. It mutes the mic while TTS is still queued/playing plus a tail window (`EMBER_SPEAK_TAIL_S`, default 1.8s) so the agent cannot respond to its own speech. Switch back to ElevenLabs' `DefaultAudioInterface` with `EMBER_AUDIO=default` only if server-side VAD is known-good for the room.
- `cv/virtual_keyboard.py` is a **standalone subprocess** (not imported) launched by `ActionDispatcher._tool_keyboard` when the voice agent calls `keyboard` (show/hide/toggle). It draws a dwell-typing on-screen keyboard in its own OpenCV window and emits keys through a second `evdev.UInput` device. Dwell-only is intentional — a click would steal focus from the target app. If you refactor it, do not turn it into an in-process import: it must stay out of the CV/voice event loops.
- `tts/router.py` + `tts/service.py` provide a FastAPI-mounted TTS router and an async `synthesize()` used by the bridge. Audio output tries `sounddevice`+`pydub` first, falls back to spawning `mpv`.

### 4. Browser onboarding (`server/`, `web/`)

- `server/main.py` is a FastAPI app serving `web/dist/` as SPA, the `/api/profile` read/write, `/api/launch` (spawns `axis.py` as a detached subprocess — only one at a time, tracked in `_cv_proc`), `/api/stop`, `/api/status`, and `/api/config`. API keys are never returned to the browser.
- `web/` is React + Vite + Tailwind, uses `@mediapipe/tasks-vision` so all browser-side capability detection happens client-side (server never touches the webcam). Pages in `web/src/pages/` are a wizard: Welcome → Discover → Configure → Practice → Done.
- Package manager is **pnpm**, pinned via `packageManager` in `web/package.json`. Do not use npm.

## Working rules specific to this repo

- **Latency is the product.** CV→driver end-to-end stays under ~33ms. Any change that adds perceptible lag does not ship. The grabber thread, `model_complexity=0`, `refine_landmarks=False`, and 640×480 capture are all there for this reason — do not "improve" them without measuring.
- **`uinput` output is what makes Axis real.** Do not ship a version where gestures only control an in-app Axis UI. That is exactly what every failed competitor (Camera Mouse, Enable Viacam, GazePointer) did. If you are tempted, escalate.
- **Variance-driven auto-discovery is the differentiator.** Do not replace onboarding with a manual "pick your gesture from a list" flow under time pressure.
- **Both pipelines share only `ActionDispatcher`.** Keep CV and voice independent otherwise — they have different latency budgets (CV: 33ms; voice: 1–3s is fine).
- **Mapping is hot-reloaded.** `mapping.py` watches mtime. Edits to `~/.ember/profile.json` or `mapping.json` take effect on the next frame — no restart.
- **`mapping.json` in repo root is legacy.** New code should read/write `~/.ember/profile.json` via `cv/profile.py` helpers. Repo-local `mapping.json` only applies when no profile exists.
- **Secrets live in `.env`** (loaded by `python-dotenv`). `.env.example` lists every var the app reads. Never hardcode `ELEVENLABS_API_KEY`, `PICOVOICE_ACCESS_KEY`, or `ELEVENLABS_AGENT_ID`.
- **Non-Linux paths are preview-only.** `VirtualMouse()` raises on non-Linux; `pyautogui` import is guarded because it fails on Wayland. Don't assume either works — check `_HAS_PYAUTOGUI` / catch `RuntimeError`.
- **Out of scope** (roadmap only, do not build unless asked): scanning mode, action wheel, Windows/macOS uinput equivalents, multi-profile save, cloud sync.

## Where to look when…

- Adding a new detectable signal → `cv/sources.py` (extract), then `cv/mapping.py` (wire an action to it), then add to `capabilities`/`bindings_from_capabilities` in `cv/profile.py` and to `cv/onboarding.py` tests.
- Adding a new voice tool → `tools/actions.py` (add to `TOOL_SCHEMAS` + `get_client_tools()` + implement `_tool_<name>`), then `python -m tools.sync_agent_tools` to register it on the ElevenLabs workspace and attach it to the agent. The per-session conversation override also carries the schema, so the tool works immediately, but without the sync step the agent loses it across sessions that don't go through the override path.
- Changing cursor feel → `cursor_sensitivity` + `filter.min_cutoff`/`filter.beta` in `~/.ember/profile.json` or `mapping.json`. For code changes, `cv/filters.py` (OneEuroFilter) and `MappingDispatcher._handle_cursor` in `cv/mapping.py`.
- Changing onboarding copy/flow → native OpenCV wizard in `cv/onboarding.py`; browser wizard pages in `web/src/pages/`.
