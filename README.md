# ember — Axis prototype

A webcam-only accessibility input layer. Axis turns face and hand motion into
real OS-level mouse + keyboard events (via `uinput` on Linux), optionally
paired with a voice agent that can launch apps, search the web, and open an
on-screen dwell-typing keyboard.

Full product brief: `vision.md`.
Windows/macOS preview-only setup: `README_WINDOWS.md`.
Contributor map + architectural invariants: `CLAUDE.md`.

---

## What works on which OS

| OS | Camera preview + landmarks | Virtual cursor + click | Virtual keyboard | Voice pipeline |
|---|:---:|:---:|:---:|:---:|
| Linux | yes | yes (`uinput`) | yes (`uinput`) | yes |
| Windows | yes | **no** — preview only | no | untested |
| macOS | yes (with camera permission) | **no** — preview only | no | untested |

Cursor + keyboard injection rely on Linux `uinput`. On other platforms the CV
pipeline runs in preview-only mode (skeleton + gesture detection visible, no
OS events).

---

## Linux setup (Arch / Ubuntu)

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Get the code
git clone https://github.com/Matusvec/ember.git
cd ember

# venv + deps
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
  "mediapipe==0.10.14" opencv-python evdev \
  fastapi uvicorn python-dotenv \
  pydub sounddevice numpy \
  elevenlabs pvporcupine

# One-time per boot: grant uinput write access
sudo chmod 0666 /dev/uinput
```

Permanent `uinput` fix (survives reboot):

```bash
sudo usermod -a -G input $USER
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
# then LOG OUT and back in
```

There is no `requirements.txt` / `pyproject.toml`. If you add a new top-level
import to `axis.py`, `server/main.py`, `voice/`, or `tools/actions.py`, update
the install command above.

---

## Running

The primary entry point is `axis.py`. On first launch it walks you through
capability-based onboarding, writes `~/.ember/profile.json`, then starts the
CV loop (and voice pipeline if applicable).

| What you want | Command |
|---|---|
| Full app (CV + optional voice, onboarding on first launch) | `.venv/bin/python axis.py` |
| Skip onboarding / force re-onboard | `python axis.py --no-onboard` / `python axis.py --onboard` |
| Enable voice pipeline | `python axis.py --voice` |
| Headless / picture-in-picture preview | `python axis.py --no-preview` or `--pip` |
| Raw CV preview only (legacy, no onboarding/voice) | `python cv/skeleton_preview.py` |
| Browser onboarding server | `python -m server` (binds `127.0.0.1:8000`, serves `web/dist/`) |
| Web dev server | `cd web && pnpm install && pnpm dev` (Vite on `:5173`) |
| Web production build | `cd web && pnpm build` |
| Web typecheck | `cd web && pnpm typecheck` |
| Install/uninstall Linux autostart | `python axis.py --install-autostart` / `--uninstall-autostart` |
| Sync voice tool schemas to ElevenLabs agent | `python -m tools.sync_agent_tools` (`--dry-run` to preview) |

Package manager for `web/` is **pnpm** (pinned via `packageManager`). Do not
use npm.

---

## Default controls (CV)

The bindings you get depend on your profile — the onboarding wizard picks
them based on what it detects you can reliably do. The defaults on a fully
motor-able user look like:

| Input | Action |
|---|---|
| **Index fingertip** (yellow circle) | moves cursor |
| **Open mouth** | left-click hold — close mouth to release |
| Press **`c`** in window | toggle cursor control on/off |
| Press **`r`** in window | record a new gesture template |
| Press **`q`** in window | quit |

Bindings live in `~/.ember/profile.json` and are **hot-reloaded** on mtime
change — edits take effect on the next frame, no restart needed. The
repo-local `mapping.json` is a legacy fallback used only when no profile
exists.

---

## Voice pipeline (opt-in)

Runs on a dedicated thread + asyncio loop. Independent of the CV loop except
through the shared `tools.actions.ActionDispatcher`.

Flow: **wake word** (Picovoice Porcupine, `AXIS_WAKE_KEYWORD`, default
`computer`) → **session** (ElevenLabs Conversational AI websocket) → session
ends → back to wake-listening.

For users whose profile prefers voice-first control (no hands, no keyboard),
`axis.py` sets `EMBER_VOICE_AUTO_WAKE=1`, which opens the ConvAI session on
startup and auto-restarts it via a watchdog — the user never presses a key
or says a wake word.

### Tools the agent can call

Defined in `tools/actions.py` as `TOOL_SCHEMAS` + handlers in `get_client_tools()`:

- **`launch_app`** — open Chrome, Firefox, Slack, files, terminal, etc.
  Falls back to `xdg-open` for anything not in the table.
- **`search_web`** — open a Google / DuckDuckGo / YouTube results page.
- **`keyboard`** — show/hide/toggle the on-screen virtual keyboard.
- **`narrate_screen`**, **`type_text`**, **`click`**, etc. — see `TOOL_SCHEMAS`.

When you add a new tool, update both the schema and the handler dict, then
run `python -m tools.sync_agent_tools` so the ElevenLabs workspace has a
persistent tool record attached to the agent.

### Half-duplex audio

`cv/half_duplex_audio.py` is the default `audio_interface` for the ElevenLabs
`Conversation`. It mutes the microphone while TTS is queued/playing and for
a tail window after (`EMBER_SPEAK_TAIL_S`, default `1.8`s) so the agent
cannot respond to its own speech. Bump the tail to 2.5+ on loud speakers or
echoey rooms. Set `EMBER_AUDIO=default` to disable and rely on server-side
VAD only.

### Virtual keyboard

`cv/virtual_keyboard.py` is a **standalone subprocess** — spawned and killed
by `ActionDispatcher._tool_keyboard` when the voice agent calls `keyboard`.
It draws a key grid in its own OpenCV window and types keys after 600ms of
cursor dwell, through a second `uinput` device (so focus stays in the target
app). Do not import it in-process — it must stay off the CV/voice loops.

---

## Browser onboarding

Alternative to the native OpenCV wizard. `server/main.py` is a FastAPI app
that serves the `web/` React+Vite+Tailwind SPA and exposes:

- `GET/POST /api/profile` — read/write `~/.ember/profile.json`
- `POST /api/launch` — spawn `axis.py` as a detached subprocess (one at a time)
- `POST /api/stop`, `GET /api/status`
- `GET /api/config`

Webcam access is **client-side only** via `@mediapipe/tasks-vision` — the
server never touches the camera. API keys are never returned to the browser.

---

## Environment variables

Copy `.env.example` to `.env` and fill in real values. `.env` is gitignored.

| Var | Purpose |
|---|---|
| `ELEVENLABS_API_KEY` | ElevenLabs account key |
| `ELEVENLABS_AGENT_ID` | Conversational AI agent id |
| `ELEVENLABS_VOICE_ID` | (optional) override default voice |
| `PICOVOICE_ACCESS_KEY` | Porcupine wake word |
| `AXIS_WAKE_KEYWORD` | built-in keyword (e.g. `computer`, `jarvis`) |
| `AXIS_WAKE_KEYWORD_PATH` | path to a custom `.ppn` file |
| `EMBER_VOICE_AUTO_WAKE` | `1` to skip wake word (auto-set by `axis.py` for voice-first profiles) |
| `EMBER_SPEAK_TAIL_S` | mic-mute tail after TTS ends (default `1.8`) |
| `EMBER_AUDIO` | `half-duplex` (default) or `default` |
| `AXIS_CONTINUOUS_NARRATION` | `1` enables continuous screen narration |
| `AXIS_NARRATION_INTERVAL` | seconds between narration polls |
| `AXIS_CACHE_DIR` | TTS audio cache location |

Never hardcode any of the keys — always load via `python-dotenv`.

---

## Architecture in 30 seconds

Three independent subsystems. See `CLAUDE.md` for the full map.

1. **CV pipeline** (`cv/`, `axis.py` → `cv/skeleton_preview.py`): 30fps
   MediaPipe loop, latency ≤33ms end-to-end. Emits signals → `mapping.py`
   dispatcher → `cursor.py` (`VirtualMouse` over `evdev.UInput`).
2. **Profile + mapping** (`cv/profile.py`, `contracts/`): `~/.ember/profile.json`
   is the source of truth. Capability booleans → bindings + an
   `interaction_mode` (`full` / `voice_first` / `visual_only` / `motor_limited`).
3. **Voice pipeline** (`voice/`, `tools/`, `tts/`, opt-in): wake → ConvAI
   session → tool calls through `ActionDispatcher` (the single shared
   boundary between CV and voice). Half-duplex audio prevents self-response;
   virtual keyboard spawned as a subprocess on demand.

Browser onboarding (`server/`, `web/`) is the newer alternative to the
native OpenCV wizard.

---

## Not in scope (yet)

Scanning mode, action wheel, Windows/macOS `uinput` equivalents,
multi-profile save, cloud sync. Stay on the core demo path.
