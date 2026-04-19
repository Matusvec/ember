# axis/main.py  (integration snippet — merge with your existing main.py)
#
# 1. pip install elevenlabs fastapi uvicorn
# 2. Add ELEVENLABS_API_KEY to your .env
# 3. Include the router as shown below

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tts import tts_router   # adjust import path to match your project layout

app = FastAPI(title="Axis")

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