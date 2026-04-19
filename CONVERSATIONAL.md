# Making Axis conversational — next phase for the voice layer

The current TTS stack is output-only. This document is the roadmap for the second half: **letting users talk to Axis and have it act on what they say.**

Written so George can pick it up and ship it.

---

## TL;DR

Add three things on top of what already exists:

1. **STT** — turn the user's voice into text
2. **Intent parser** — turn text into an action (or a question back to them)
3. **Response handoff** — feed the response text into the existing `synthesize()` so the user hears the answer

All three should run in a **separate asyncio loop** from the CV pipeline so nothing touches the 30fps cursor path. Voice is allowed to be 1–3 seconds latent; CV is not.

---

## Architecture

```
         Microphone
              │
              ▼
   ┌──────────────────┐
   │ Wake-word watch  │  Porcupine / "Hey Axis"
   └─────────┬────────┘
             │ triggered
             ▼
   ┌──────────────────┐
   │ Speech-to-Text   │  Whisper local / Groq / ElevenLabs STT
   └─────────┬────────┘
             │ text
             ▼
   ┌──────────────────┐
   │ Intent parser    │  Claude/GPT with function-calling tools
   │  (LLM + tools)   │
   └─────────┬────────┘
             │
   ┌─────────┼──────────────┐
   │         │              │
   ▼         ▼              ▼
  Action   Response       Confirmation
 dispatcher  text           needed?
   │         │              │
   │         ▼              ▼
   │      synthesize()   synthesize()
   │      (existing TTS) (existing TTS)
   │
   ▼
 Virtual Mouse / Keyboard
 (the CV pipeline's driver)
```

**Key rule:** the voice layer shares nothing with the CV layer except the **action dispatcher**. Both emit into the same dispatcher. Neither owns the other's latency budget.

---

## Three deployment paths — pick one

### Path A — ElevenLabs Conversational AI (fastest)

Use [ElevenLabs Conversational AI](https://elevenlabs.io/docs/conversational-ai). One SDK does STT + LLM + TTS. Sub-2-second round-trip. Tool-calling built in.

**Pros:**
- Ships in ~3 hours of work
- Same vendor as your TTS already — one API key, one bill
- Their LLM and STT are tuned for low-latency conversation

**Cons:**
- Less control over the LLM prompt / tool semantics
- Paid usage scales with conversation minutes
- Lock-in

**Best for:** getting the demo working this weekend.

### Path B — DIY stack (most control)

Stitch it yourself:

| Layer | Library | Notes |
|---|---|---|
| Wake word | `pvporcupine` (Picovoice) | Local, free for personal/research. Custom wake words need signup. |
| STT | `openai-whisper` (local) or `groq` (remote, ~200ms) | Whisper is 100% offline; Groq is faster but needs network. |
| LLM + tools | Anthropic SDK (`claude-sonnet-4-5` or `claude-opus-4-7`) with function-calling | Give it a list of tool schemas that correspond to action dispatcher entries. |
| TTS | The existing `tts/service.py` | Reuse as-is. |

**Pros:**
- You own every layer and can tune them independently
- Whisper local works offline
- Claude's tool-calling is excellent for structured intent

**Cons:**
- 10–15 hours of integration
- More failure surfaces (each layer can flake)

**Best for:** post-demo productization.

### Path C — Hybrid

Use **Whisper local + Claude tool-calling + existing ElevenLabs TTS**. Drops the one product we don't want (ElevenLabs' conversational wrapper) and keeps everything else.

**Recommended for most teams.** About 6–8 hours.

---

## File layout to add

Keep it parallel to the existing `tts/`:

```
voice/
├── __init__.py
├── wake.py          # Porcupine wake-word watcher
├── stt.py           # Whisper / Groq STT wrapper
├── intent.py        # Claude client + tool schemas
├── router.py        # FastAPI /voice endpoints (optional)
└── bridge.py        # Glue: STT output → intent → action dispatch

tools/
├── __init__.py
└── actions.py       # Tool schemas exposing the action dispatcher to the LLM
```

`tools/actions.py` is the critical boundary — it's where the LLM's tool calls turn into concrete calls on the CV layer's `VirtualMouse` / mapping dispatcher.

---

## Minimum viable tool schema

Define exactly the actions Axis can take. Start with six — expand from here:

```python
TOOLS = [
    {
        "name": "move_cursor",
        "description": "Move the mouse cursor to a named screen region.",
        "input_schema": {
            "type": "object",
            "required": ["region"],
            "properties": {
                "region": {
                    "enum": ["top-left", "top-center", "top-right",
                             "middle-left", "middle", "middle-right",
                             "bottom-left", "bottom-center", "bottom-right"]
                }
            }
        }
    },
    {
        "name": "click",
        "description": "Fire a mouse click.",
        "input_schema": {
            "type": "object",
            "properties": {
                "button": {"enum": ["left", "right", "middle"], "default": "left"}
            }
        }
    },
    {
        "name": "scroll",
        "description": "Scroll the active window.",
        "input_schema": {
            "type": "object",
            "required": ["direction"],
            "properties": {
                "direction": {"enum": ["up", "down"]},
                "amount": {"type": "integer", "default": 3}
            }
        }
    },
    {
        "name": "type_text",
        "description": "Type literal text via the virtual keyboard.",
        "input_schema": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}}
        }
    },
    {
        "name": "launch_app",
        "description": "Open an application by well-known name (Chrome, Firefox, Slack, etc).",
        "input_schema": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}}
        }
    },
    {
        "name": "answer",
        "description": "Respond conversationally without taking an action. Use when the user asks a question or makes small talk.",
        "input_schema": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}}
        }
    }
]
```

The LLM picks exactly one tool per turn. `answer` is the fallback for "user said something that doesn't map to an action." That response text goes straight to the existing `synthesize()` → user hears the guide talking back.

---

## Safety — the one thing you cannot skip

The moment voice can execute actions, someone can say "delete all my files" and Axis will try. Three mitigations:

### 1. Allowlist only

Your action dispatcher should only expose **safe actions**. No shell execution. No file deletion. No arbitrary app launch — only a curated list. If the LLM picks a tool not in the list, you refuse.

### 2. Confirmation for anything destructive

For actions flagged as `destructive: true` in their schema (close window, delete file, submit form, etc.), the flow becomes:

```
User: "Close this window"
Guide:  "About to close the current window. Say 'yes' to confirm."
[wait up to 5 seconds for confirmation gesture or utterance]
If confirmed → dispatch
Else → "Cancelled."
```

The confirmation itself can be a voice "yes" OR a dwell-click on a confirmation overlay. Give both paths so users who can't speak still control the safety gate.

### 3. Prompt injection resistance

The LLM system prompt must not be overridable by the user's utterance. Pin it at the start of every turn. Do **not** let the user's voice include text like "ignore previous instructions" that the LLM would obey. A simple defense:

- System prompt: locked, single string, loaded once
- User message: only the STT output, clearly marked
- No "system" messages derived from user voice

---

## Integration with the existing TTS stack

Almost nothing in `tts/` changes. You add:

**1. A `/voice/ws/conversation` WebSocket** in a new `voice/router.py` that:
- Accepts audio chunks from the browser mic
- Pipes them through STT
- Sends the transcript to the intent parser
- Fires the resulting action
- Streams the response audio back using `synthesize_stream()` (already in `tts/service.py`)

**2. A shared `ActionDispatcher`** that both:
- The voice pipeline calls from intent handling
- The CV pipeline (in the `matus` branch's `mapping.py`) calls from gesture events

Both use the same `VirtualMouse` under the hood. No double-writes. No competing drivers.

**3. Pre-warmed confirmation phrases** added to `voice_guide.py`:

```python
CONFIRMATION_PHRASES = {
    "confirm_close": "About to close the current window. Say yes to confirm.",
    "confirm_delete": "About to delete this. Say yes to confirm.",
    "cancelled": "Cancelled.",
    "not_understood": "I didn't catch that. Try again?",
    "tool_unavailable": "I can't do that one yet.",
}
```

Add them to `PHRASES` so the cache prewarm covers them.

---

## Wake-word decision

Three options for "how does the guide start listening":

| Option | UX | Implementation |
|---|---|---|
| **Always listening** | Most natural. User just talks. | Continuous STT; costly, privacy-messy. |
| **Wake word ("Hey Axis")** | Feels like Siri/Alexa. | Porcupine local detection. Recommended. |
| **Gesture-triggered** | "Do the mouth-open gesture to start talking." | Ties voice to CV — interesting accessibility angle. |

**Best default:** wake word. Cheapest compute, clearest UX, user in control.

**Accessibility consideration:** make the wake phrase **configurable**. Users with dysarthria may not reliably produce "Hey Axis" — let them pick any phrase they can consistently speak. Porcupine supports custom wake words.

---

## Latency budget

Target end-to-end: **under 2.5 seconds** from end-of-user-utterance to start-of-response-audio. Rough budget:

| Stage | Target |
|---|---|
| STT (on utterance end) | 200–500ms |
| LLM with tool-calling | 600–1200ms |
| Tool dispatch (for action) | <50ms |
| TTS first-byte | 300–500ms |
| **Total time-to-first-audio** | **~1.5–2.3s** |

Using the existing `synthesize_stream()` for the TTS step is important — it starts audio before the full sentence is synthesized.

If you hit 3+ seconds, the UX gets janky. Log per-stage latencies from day one so you can see where time goes.

---

## Integration sequence — what to build first

**Hour 1–2: plumbing**
- Add `voice/` package skeleton
- `voice/stt.py` with a `transcribe(audio_bytes) -> str` function using Whisper or Groq
- Test: speak into a file, get text out

**Hour 2–4: intent parser**
- `voice/intent.py` with Claude client, 3 tools (`move_cursor`, `click`, `answer`)
- Test: pass text in, get tool call out

**Hour 4–6: bridge**
- `voice/bridge.py`: STT → intent → action dispatcher → TTS response
- Wire through a command-line entrypoint for testing without frontend

**Hour 6–8: wake word + FastAPI**
- Porcupine wake-word watcher in `voice/wake.py`
- Expose `/voice/ws/conversation` in the FastAPI app
- End-to-end demo works: say "Hey Axis, click", Axis clicks

**Hour 8–10: expand tools**
- Add `scroll`, `type_text`, `launch_app`
- Add confirmation flow for destructive actions

**Hour 10–12: polish**
- Error paths, "I didn't catch that" handling, prompt injection hardening
- Per-stage latency logging

---

## Demo script when this is all working

> Judge is already watching the CV demo. Head cursor, mouth click, arm taped.
>
> Cut to voice mode: *"Hey Axis, open Chrome."*
> Chrome opens. Matus keeps using his head for the cursor.
>
> *"Hey Axis, go to YouTube."*
> YouTube loads.
>
> *"Hey Axis, read me the first result title."*
> The guide speaks the title.
>
> *"Hey Axis, click it."*
> Video plays.
>
> *"Hey Axis, pause."*
> Pauses.
>
> **Close: "CV when I can move. Voice when I can't. Neither requires the other. Both free."**

That's the demo that wins.

---

## Open questions to sort before building

1. **Which path (A, B, or C)?** This branches the first 3 hours.
2. **Where does the LLM run — local or cloud?** Claude API is cloud. Local LLMs (llama.cpp, Ollama) are slower but work offline. For the demo, cloud is fine.
3. **Is the wake word user-configurable at setup, or hardcoded?** For demo: hardcoded "Hey Axis." For product: configurable.
4. **Do we need an "undo last action" tool?** Probably yes. Saves the demo when the LLM does something wrong.
5. **Does the guide speak continuously (reading what's on screen) or only respond to commands?** I'd vote only-respond for MVP. Continuous narration is a v2 feature.

---

## Summary

Existing TTS layer: **done, don't touch.**
Next phase: **three new modules (stt, intent, bridge) + one FastAPI endpoint + a tool schema.**
Integration with CV side: **through a shared action dispatcher, not through file imports.**

— Matus (via Claude)
