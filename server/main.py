"""Ember web server — FastAPI app for the browser-based setup flow.

Serves the built React SPA at /, the profile API at /api/*, and the TTS
router at /tts/*. All capability detection happens in the browser via
MediaPipe tasks-vision; this server never touches the webcam.

Start with:
    uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
or
    python -m server
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"
PROFILE_DIR = Path.home() / ".ember"
PROFILE_PATH = PROFILE_DIR / "profile.json"


# ---- TTS router (existing) --------------------------------------------------

from tts.router import tts_router, tts_startup


# ---- Lifespan ---------------------------------------------------------------

_cv_proc: Optional[subprocess.Popen] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await tts_startup()
    except Exception as exc:
        print(f"[server] TTS prewarm skipped: {exc}", flush=True)
    yield
    global _cv_proc
    if _cv_proc is not None:
        try:
            _cv_proc.send_signal(signal.SIGINT)
            _cv_proc.wait(timeout=3)
        except Exception:
            try:
                _cv_proc.kill()
            except Exception:
                pass


app = FastAPI(title="Ember", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(tts_router, prefix="/tts")


# ---- Config endpoint --------------------------------------------------------

@app.get("/api/config")
def get_config() -> dict[str, Any]:
    """Public config the browser needs — agent id, voice id, etc.

    API keys are NEVER returned. ConvAI uses a public agent id + websocket
    that authenticates per-session on the client.
    """
    return {
        "elevenlabs_agent_id": os.getenv("ELEVENLABS_AGENT_ID", ""),
        "elevenlabs_voice_id": os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        "profile_exists": PROFILE_PATH.exists(),
    }


# ---- Profile endpoints ------------------------------------------------------

class ProfilePayload(BaseModel):
    capabilities: dict[str, bool]
    bindings: list[dict[str, Any]]
    voice_enabled: bool = False
    cursor_sensitivity: float = 4000.0
    filter: dict[str, float] = {"min_cutoff": 1.0, "beta": 0.05}


@app.get("/api/profile")
def get_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        raise HTTPException(404, "no profile yet")
    return json.loads(PROFILE_PATH.read_text())


@app.post("/api/profile")
def save_profile(payload: ProfilePayload) -> dict[str, Any]:
    import time
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": 2,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "capabilities": payload.capabilities,
        "bindings": payload.bindings,
        "voice_enabled": payload.voice_enabled,
        "cursor_sensitivity": payload.cursor_sensitivity,
        "filter": payload.filter,
    }
    tmp = PROFILE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(PROFILE_PATH)
    return {"ok": True, "path": str(PROFILE_PATH)}


# ---- Launch endpoint --------------------------------------------------------

class LaunchOptions(BaseModel):
    preview: str = "pip"  # "pip" | "off" | "normal"
    voice: bool | None = None


@app.post("/api/launch")
def launch_runtime(opts: LaunchOptions | None = None) -> dict[str, Any]:
    """Start the Python CV pipeline (axis.py) in a detached subprocess.

    By default, launches with --pip so users see a small corner preview that
    doesn't block other apps. Use preview="off" for fully headless.
    """
    global _cv_proc
    if _cv_proc is not None and _cv_proc.poll() is None:
        return {"ok": True, "status": "already running", "pid": _cv_proc.pid}

    opts = opts or LaunchOptions()
    python = sys.executable
    axis_path = ROOT / "axis.py"
    args = [python, str(axis_path), "--no-onboard"]
    if opts.preview == "off":
        args.append("--no-preview")
    elif opts.preview == "pip":
        args.append("--pip")
    # "normal" → no preview flag, uses default full window.
    want_voice = opts.voice if opts.voice is not None \
        else os.getenv("EMBER_AUTOSTART_VOICE", "0") == "1"
    if want_voice:
        args.append("--voice")

    _cv_proc = subprocess.Popen(
        args,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"ok": True, "status": "launched", "pid": _cv_proc.pid}


@app.post("/api/stop")
def stop_runtime() -> dict[str, Any]:
    global _cv_proc
    if _cv_proc is None or _cv_proc.poll() is not None:
        _cv_proc = None
        return {"ok": True, "status": "not running"}
    try:
        _cv_proc.send_signal(signal.SIGINT)
        _cv_proc.wait(timeout=3)
    except Exception:
        try:
            _cv_proc.kill()
        except Exception:
            pass
    _cv_proc = None
    return {"ok": True, "status": "stopped"}


@app.get("/api/status")
def runtime_status() -> dict[str, Any]:
    running = _cv_proc is not None and _cv_proc.poll() is None
    return {"running": running, "pid": _cv_proc.pid if running else None}


# ---- Static serving of the built SPA ---------------------------------------

if WEB_DIST.exists():
    # Serve assets under /assets/* and fall through to index.html for SPA routes.
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        # Anything not matched above → serve index.html and let React Router handle it.
        return FileResponse(WEB_DIST / "index.html")
else:
    @app.get("/")
    def dev_root() -> JSONResponse:
        return JSONResponse({
            "msg": "Web app not built. Run `cd web && pnpm install && pnpm build`, "
                   "or `pnpm dev` and point your browser at http://localhost:5173.",
        })
