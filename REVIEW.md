# ElevenLabs TTS integration — review notes for George

Matus reviewed this branch before merging into the main work on `matus`. Below is what's good, what needs fixing, and how to wire it into the rest of the project.

---

## TL;DR

1. **There is a critical bug on `tts/service.py` line 31 that also leaked the ElevenLabs API key to GitHub.** Matus has already rotated the key so the old one is dead. Fix the code before the next push. See **Security fix** below.
2. The TTS layer itself is well-built. Keep it — we are using it.
3. It only **speaks**. It does not **listen**. For the "talk to the guide" vision, STT and intent parsing still need to be added. See **What's missing** below.

---

## 🚨 Security fix — do this first

### The bug

```python
# tts/service.py, line 31
api_key = os.getenv("sk_cacfb86445e65d49434984773eeed5a98dc04a81a4bf0cdb")
```

`os.getenv()` takes the **name** of an environment variable as its argument. You passed the actual secret value as the name, so:

1. It looks up an env var literally called `sk_cacfb86...`, finds nothing, and returns `None`.
2. The `EnvironmentError` always fires — **this code cannot have worked in testing.**
3. The real key is now in git history on a pushed branch. That means every fork, clone, and cached GitHub view has it.

### The fix

```python
# tts/service.py
def get_client() -> AsyncElevenLabs:
    global _client
    if _client is None:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ELEVENLABS_API_KEY is not set. "
                "Add it to your .env file or environment."
            )
        _client = AsyncElevenLabs(api_key=api_key)
    return _client
```

Then put the new key in a `.env` file at the repo root:

```
ELEVENLABS_API_KEY=sk_<your_new_rotated_key>
```

Load it in your FastAPI entrypoint before anything imports from `tts/`:

```python
# main.py (or wherever your app starts)
from dotenv import load_dotenv
load_dotenv()   # reads .env into os.environ
```

If you don't already have `python-dotenv` installed:

```bash
pip install python-dotenv
```

### Add `.env` to `.gitignore` RIGHT NOW

If the repo doesn't have a `.gitignore`, create one at the root:

```
.env
.env.*
!.env.example
__pycache__/
*.pyc
.venv/
```

Commit the `.gitignore` separately from any code change. This is the single most important line you will write this hackathon.

### Do not scrub history unless you're comfortable with it

The old key is already in GitHub's mirror and in every clone. Rotating the key (which is done) is the important part. Trying to `git filter-branch` or `git filter-repo` the key out of history is error-prone and doesn't fully work if anyone has already forked. Focus on: rotate key, fix code, add `.env`, move on.

---

## 🔒 API-key hygiene — how to not do this again

Three rules. Internalize them.

1. **Never paste a secret into source code.** Not even briefly. Not even "I'll remove it before I commit". You won't.
2. **All secrets live in `.env` files that are `.gitignore`d.** No exceptions.
3. **Before every `git push`, run `git diff --cached | grep -i "sk_\|api_key\|secret\|password"`** on what you're about to push. If anything comes back, stop and look at it.

Optional but recommended:

- Install a pre-commit hook that scans for secrets: `pip install detect-secrets` then `detect-secrets scan` before commits. Or use [gitleaks](https://github.com/gitleaks/gitleaks).
- GitHub has free **secret scanning** on public repos. If a key does leak, GitHub will often email you within minutes. Take those emails seriously.

---

## What's great in this branch

Keeping the design you chose — no rewrites needed on these pieces:

- **Disk cache keyed by `hash(voice+model+text)`.** Known phrases served in milliseconds after first call. Correct choice.
- **`prewarm()` at startup.** Makes the whole calibration flow zero-latency for the user. Nice.
- **`eleven_turbo_v2_5`** is the right model — lowest latency in the ElevenLabs lineup.
- **WebSocket `/ws/status`** for real-time gesture → audio chirps. Much faster than HTTP per event.
- **Enum-organized script bank** (`CalibrationStep`, `StatusEvent`) keeps things type-safe and easy to expand.
- **Auto-interrupt in-progress audio** when a new speech call fires — critical UX detail, easy to miss.
- **AAC endpoint (`/aac`).** This is a killer accessibility feature. Users compose text via gesture, this speaks it aloud. Tobii/Dynavox charge thousands for this. Great that you included it.
- **React hook cleanly separates concerns** — `speak*` for outbound, `useTTSStatusSocket` for real-time status push.

---

## What's missing for full voice-guide vision

Matus and I discussed wanting users to also *talk to* Axis, not just hear it. This branch is output-only. To get to the "tell the computer what to do" vision we still need:

| Missing piece | Suggested approach |
|---|---|
| **Speech-to-text** | Whisper local (offline, free) OR ElevenLabs' new STT API |
| **Wake word** | Picovoice Porcupine or OpenWakeWord (both local) |
| **Intent / command parser** | Claude or GPT with function-calling — tools map to our action dispatcher |
| **Conversational turn state** | Either DIY, or use **ElevenLabs Conversational AI** which bundles STT + LLM + TTS in one SDK |

**Recommended route:** ElevenLabs Conversational AI. You're already integrated with them. Their Conversational AI product does the whole listen → think → speak loop in one call with sub-2-second round-trip. Much faster to get to "working" than stitching Whisper + Claude + our existing TTS ourselves.

If you want more control (custom intents, specific tool calls), go modular instead: Whisper → Claude tool-calling → this TTS stack.

---

## How this integrates with the `matus` branch

`matus` has the CV pipeline (MediaPipe face/hands/pose), virtual mouse (uinput), finger-tracking cursor, mouth-as-click, and One-Euro smoothing. The TTS layer slots in cleanly — no conflicts.

### Integration path

1. Fix the API key bug (above).
2. Merge `tts/` and `useTTS.ts` into `matus`. No conflicts — these are new files.
3. Wire our gesture dispatcher to emit `StatusEvent`s over the `/ws/status` WebSocket. Every click → `"click_fired"` → audio chirp. ~5 lines of code.
4. Expose the FastAPI server (none in `matus` yet). Add it as a separate process or spawn from the preview script.
5. Later: layer STT on top for two-way conversation.

### Latency rules

- **CV loop stays 100% local.** 30fps = 33ms per frame. Never touches the network.
- **Voice layer runs alongside.** Tolerates 2–4s round-trip. Failure mode is "voice unavailable, CV still works."
- **Both layers feed the same action dispatcher.** Neither layer owns the other.

If voice ever touches the cursor loop, latency dies and the product fails. Keep them separate.

---

## Other small issues to fix while you're in here

| File | Line | Issue |
|---|---|---|
| `useTTS.ts` | 128–133 | `stop()` doesn't revoke the blob URL — minor memory leak over long sessions. Easy fix: copy the `URL.revokeObjectURL(audioRef.current.src)` pattern from `playBlob`. |
| `useTTS.ts` | 156–189 | `useTTSStatusSocket` uses `useTTSInternal` which creates a *second* `audioRef`, so `useTTS().stop()` won't cancel audio coming from the WebSocket. Unify the audio ref across both hooks (module-level singleton, or a shared context). |
| `tts/voice_guide.py` | 144–148 | `announce_tts_output` is a pass-through with no added value — either remove it and call `synthesize()` directly, or give it actual formatting logic. |
| `tts/service.py` | 80–89 | The `isinstance(audio_bytes, bytes)` fallback handles a generator case, but if it hits the `b"".join([chunk async for chunk in audio_bytes])` path it'll block the whole event loop because nothing in that branch yields. Either always use the stream API or document which SDK version this assumes. |
| `tts/router.py` | 190–205 | `on_event("startup")` is deprecated in newer FastAPI. Use the `lifespan` context manager instead: `app = FastAPI(lifespan=lifespan)`. Not urgent — current form still works. |

---

## Summary — what to do next, in order

1. **Rotate key** ✅ (done)
2. **Fix `tts/service.py` line 31** → real `os.getenv("ELEVENLABS_API_KEY")`.
3. **Create `.env`** at repo root with the new key.
4. **Create `.gitignore`** that includes `.env`.
5. **Install and call `python-dotenv`** in the FastAPI entrypoint.
6. Push the fixes to `feat/elevenlabs-integration`.
7. Ping Matus — we'll merge into `matus` and wire up the gesture event WebSocket.

Clean work overall, George. The architecture is right and the caching strategy is the kind of thing that'll make the demo feel magic. Just lock down the secrets and we're in good shape.

— Matus (via Claude)
