# axis/main.py  (integration snippet — merge with your existing main.py)
#
# 1. pip install elevenlabs fastapi uvicorn python-dotenv
# 2. cp .env.example .env  →  fill in ELEVENLABS_API_KEY
# 3. Integrate as shown below

from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()   # must run before any tts/ import reads os.getenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tts.router import tts_router, tts_startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kick off background pre-warm of all known TTS phrases.
    # Replaces the deprecated on_event("startup") pattern.
    await tts_startup()
    yield
    # (add any shutdown logic here if needed)


app = FastAPI(title="Axis", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],   # React dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tts_router, prefix="/tts")

# ... rest of your routes (CV pipeline websocket, gesture mapping API, etc.)


# ─────────────────────────────────────────────────────────────────────────────
# USAGE EXAMPLES
# ─────────────────────────────────────────────────────────────────────────────

# ── 1. Calibration flow (Python side, e.g. in your CV pipeline) ──────────────
#
# from tts import synthesize, CalibrationStep, CALIBRATION_SCRIPTS
#
# async def run_calibration():
#     # Step 1 — welcome
#     audio = await synthesize(CALIBRATION_SCRIPTS[CalibrationStep.WELCOME])
#     # ... play audio via your preferred method (sounddevice, playsound, etc.)
#
#     await asyncio.sleep(90)   # scanning window
#
#     inputs = detect_candidate_inputs()   # your variance analysis
#     text = announce_detected_inputs(inputs)
#     audio = await synthesize(text)
#     # ... play audio


# ── 2. React — calibration UI ────────────────────────────────────────────────
#
# import { useTTS } from "../hooks/useTTS";
#
# function CalibrationScreen() {
#   const { speakCalibrationStep, speakFoundInputs, speakStatus } = useTTS();
#
#   useEffect(() => {
#     speakCalibrationStep("welcome");   // fires on mount
#   }, []);
#
#   const handleScanComplete = (inputs) => {
#     speakFoundInputs(inputs);          // "I found 4 reliable inputs: ..."
#   };
#
#   const handleMapped = (gesture, action) => {
#     speakMapping(gesture, action);     // "Head tilt left mapped to mouse left."
#   };
# }


# ── 3. React — AAC output triggered by gesture ───────────────────────────────
#
# function AACPanel() {
#   const { speakAAC } = useTTS();
#   const [composedText, setComposedText] = useState("");
#
#   // Called by your gesture engine when the user fires their "speak" gesture
#   const onSpeakGesture = () => {
#     if (composedText) speakAAC(composedText);
#   };
#
#   return <div>...</div>;
# }


# ── 4. Status WebSocket (React — gesture driver component) ───────────────────
#
# import { useTTSStatusSocket } from "../hooks/useTTS";
#
# function GestureDriver() {
#   const { emitStatus } = useTTSStatusSocket();
#
#   // In your gesture detection callback:
#   const onGestureDetected = () => emitStatus("gesture_detected");
#   const onClickFired      = () => emitStatus("click_fired");
#   const onDriverStarted   = () => emitStatus("driver_started");
# }