# Axis — Your Body. Your Controls. Your World.
### Hesburgh Hackathon 2026 — Full Project Brief

---

## The Problem

There are 5.4 million paralyzed people in the United States alone. Add children with Spinal Muscular Atrophy (SMA), Cerebral Palsy (CP), ALS, Multiple Sclerosis, spinal cord injuries, post-stroke patients, and kids in long-term hospital stays — and you have tens of millions of people who cannot use a standard computer.

The current solutions are:

| Solution | Cost | Critical Limitation |
|---|---|---|
| Eye trackers (Tobii etc.) | $3,000–$15,000 | Causes eye fatigue, drifts, fails with nystagmus |
| Sip-and-puff devices | $1,500–$5,000 | One bit of input at a time — deeply slow |
| Switch access | $200–$2,000 | One or two buttons, navigating UI takes minutes per action |
| AAC devices | $4,000–$8,000 | Communication only, not general computing |
| Voice control (Dragon etc.) | $150–$500/yr | Fails in noisy environments, requires clear speech |

Every single one of these is expensive, single-purpose, requires specialist setup, and does not give the user a *general computer.* They give a limited interface to a limited set of tasks. None of them run as system-level drivers that work with every existing app.

**The gap:** nobody has built a free, webcam-only, self-configuring general input layer that works with the existing OS and every existing application.

A webcam costs $20. Every laptop already has one built in. The hardware problem is solved. The software problem is not.

---

## The Solution — Axis

Axis is a computer vision-powered personal input configurator. It watches you for 90 seconds, automatically detects what parts of your body you can move reliably, and lets you map those movements to any keyboard shortcut, mouse action, click, or hotkey. Then it runs silently in the background as a system-level virtual input driver.

The OS sees it as a real keyboard and mouse. Every existing application works — Chrome, Minecraft, Google Docs, Zoom, Discord, everything — without modification. You are not locked into a special Axis interface. You are just using your computer, like anyone else.

---

## How It Works — Technical Architecture

Axis is composed of three distinct systems working in sequence.

### System 1 — The Movement Detector

On first run, Axis performs a guided 2-minute discovery session. It does not ask the user what they can move. It watches, and finds it automatically.

The camera runs MediaPipe's full landmark suite simultaneously:

- **Face Mesh** — 468 3D face landmarks, tracks micro-expressions at 30fps
- **Hand Landmarks** — 21 landmarks per hand, detects individual finger states
- **Pose Skeleton** — 33 body landmarks, tracks upper body and shoulder position

Over 2 minutes of natural resting movement, Axis runs a signal variance analysis on every tracked point. Landmarks that show consistent, repeatable variance above a defined threshold are flagged as **candidate controls.** Landmarks that are noisy or flat — indicating the user cannot reliably control them — are automatically excluded.

**Detectable inputs (partial list):**

| Body Region | Detectable Signals |
|---|---|
| Head | Tilt left/right, nod up/down, rotation |
| Eyes | Blink left, blink right, blink both, sustained gaze direction |
| Eyebrows | Raise left, raise right, raise both, furrow |
| Mouth | Open/close, smile, corner pull left/right, cheek puff |
| Hands | Individual finger extension, wrist rotation, fist |
| Shoulders | Shrug left, shrug right, shrug both |
| Upper body | Lean left/right, lean forward |

The discovery session outputs a ranked list: *"We found 6 reliable inputs on your body."* The user sees their face and body on screen with detected zones highlighted in real time. They confirm which feel comfortable and intentional.

### System 2 — The Mapping Layer

The user now has 4–8 confirmed inputs. The mapping UI presents these as draggable tiles that can be dropped onto action slots:

**Mouse control:**
- Head tilt → cursor direction (proportional speed based on tilt angle)
- Dwell-to-click: hold cursor still over target for 600ms → fires click (no separate gesture needed)
- Facial gesture → left click, right click, scroll up, scroll down

**Keyboard control:**
- Any gesture → any keyboard key or modifier
- Any gesture → any system shortcut (Ctrl+C, Alt+Tab, Win key, etc.)
- Any gesture → custom macro (launch app, mute mic, next track, screenshot)

**Scanning mode (for users with a single reliable input):**
A highlight box automatically scans through interactive UI elements on screen. The user's one gesture selects the currently highlighted item. Slow but functional for anyone with a single voluntary movement.

**Action wheel:**
One gesture opens a radial menu of 8 additional actions, giving users with limited inputs access to a full keyboard's worth of commands.

### System 3 — The System Driver

This is what makes Axis genuinely useful rather than a demo. Axis runs as a background process that outputs to a **virtual input device:**

- **Linux:** uinput virtual device (kernel-level, works with all X11 and Wayland applications)
- **Windows:** vJoy + SendInput hook (works with all Win32 and DirectInput applications)
- **Mac:** CGEvent tap (works with all Cocoa and Carbon applications)

The operating system sees Axis as a real keyboard and mouse. This has three critical implications:

1. **Every existing app works.** No app needs modification, a special mode, or accessibility API support.
2. **Games work.** Applications that read raw HID input — including most games — respond correctly.
3. **The user is not inside Axis.** Once configured, Axis is invisible. The user is just using their computer.

This architectural decision — system-level virtual device output — is what separates Axis from every existing accessibility app that only functions inside its own interface.

---

## Who This Is For

### Children in Long-Term Hospital Care

A 12-year-old with osteosarcoma has been in a hospital bed at Memorial Children's Hospital South Bend for 8 weeks. She has reliable head control and consistent eyebrow raises. Nothing else is dependable.

**Before Axis:** She needs a nurse or family member to operate her laptop for her. Every text message, every YouTube video, every piece of homework requires asking someone. At 2am when she cannot sleep and her family has gone home, she stares at the ceiling.

**After Axis:** Head tilt controls her cursor. Eyebrow raise clicks. Smile scrolls. She can browse the internet herself. Message her friends on Instagram. Submit her own Google Classroom assignments. Pause Netflix mid-episode. Every one of these actions was previously gated by another human being's availability. Axis gives her her autonomy back — not just practically, but psychologically.

### Kids with SMA (Spinal Muscular Atrophy)

SMA affects approximately 1 in 10,000 births. Children with Type 1 SMA have severely limited voluntary movement from infancy. Many have head control, facial muscle control, and little else.

Standard gaming, school software, and social media platforms are completely inaccessible. Axis maps their available movement to full computer control. They use the same apps their classmates use. Not a special version. The same ones. The social normalcy this creates for a child who is already isolated is immeasurable.

### Young Adults with Spinal Cord Injuries

A 19-year-old sustained a C4 spinal cord injury in a sports accident. He has head control, some facial movement, and one shoulder that moves reliably. Gaming was his primary social world before his injury.

**Before Axis:** He cannot hold a controller. Standard keyboard and mouse are impossible. Accessible gaming options are limited, expensive, and exclude most of the games his friends play.

**After Axis:** Shoulder shrug maps to a modifier key. Head tilt controls mouse. Smile fires click. He maps these to strafe, aim, and shoot in a first-person game. Not as fast as a controller — but he is in the game, with his friends, in the same session, talking on Discord at the same time. His friend group's primary social space is available to him again.

### Post-Stroke Adults

Stroke is the leading cause of long-term adult disability in the US. Roughly 800,000 Americans have a stroke each year. Many survivors have unilateral paralysis — one side of the body largely unresponsive.

A 65-year-old stroke survivor has limited left-hand movement — she can extend her index finger — and reliable head and face control. Axis maps her available movement to full computer access. She can video call her grandchildren herself. Check her own email. Research her own medical information. Cook with a recipe she found herself. These acts of independence are not small — they are the difference between a patient and a person.

---

## The Demo

The demo is 4 minutes and requires no explanation. Execution is the explanation.

**Setup:** Ask a judge to sit at a laptop. Tape one arm to the chair armrest. Tell them to send an email.

Watch them struggle for 20 seconds.

**The pitch line:** *"46 million people with motor disabilities live this every single day. The solution the market offers costs six thousand dollars. We built it for free, and it runs on the camera already built into their laptop."*

**The demo:** Open Axis. Run calibration — 90 seconds, head and face only. Show the detection UI highlighting the judge's available motions in real time. Map head tilt to mouse, eyebrow raise to click, smile to scroll.

Now let them use the computer. Browse a website. Open Spotify. Send a message in a browser app. Play 30 seconds of a simple web game.

Then untape their arm.

**The close:** *"This is Axis. Your body. Your controls. Your world."*

---

## Why Nobody Has Built This Properly Yet

Several partial solutions exist — Camera Mouse (Boston University), Enable Viacam, GazePointer, Camera Switch Access. They all share the same critical limitations:

- Mouse movement only — no keyboard output
- No automatic discovery of available inputs; require manual setup by a caregiver
- Do not output as system-level virtual input devices — only work within their own interface
- No game compatibility
- Built on older, pre-MediaPipe CV pipelines with lower accuracy and robustness
- Have not received meaningful updates in 3–7 years

Axis differs on every axis (intentional): self-configuring discovery, full keyboard and mouse output, system-level virtual device driver, modern MediaPipe landmark backbone, and designed to be set up by the user themselves in under 5 minutes with zero specialist help.

---

## Rubric Alignment

| Criterion | Score | Why |
|---|---|---|
| **Execution** | 9/10 | Core demo — head tracking + dwell click + 2 gesture keys working in Chrome and one game — is scoped to be bulletproof in 42 hours. No dependencies on external APIs that can fail. |
| **Social Impact** | 10/10 | Named population (pediatric oncology, SMA, spinal cord injury), named local partner (Memorial Children's Hospital South Bend), documented crisis (childhood hospitalization isolation + disability technology access gap). Impact is not hypothetical — it is immediate and deployable. |
| **Usability** | 10/10 | Designed for someone with minimal motor control. If a bedridden child can configure and use it in 5 minutes, any judge can use it in 90 seconds. The onboarding is the demo. |
| **Technical Merit** | 9/10 | Real-time multi-landmark variance analysis for automatic input discovery is novel engineering. System-level virtual device output is production-grade architecture. MediaPipe multi-pipeline fusion is non-trivial. Not a wrapper around an existing API. |
| **Innovation** | 10/10 | Zero existing projects do this. The self-configuring aspect — finding your available inputs automatically rather than requiring manual setup — is the key novel angle. No judge has seen this before. |
| **Total** | **48/50** | Tied with the top-rated concepts in the field analysis, with higher execution confidence. |

---

## 42-Hour Build Plan

### MVP Scope — What Must Work for Demo

The demo requires exactly these components working end-to-end:

1. MediaPipe face mesh + pose running live from webcam at stable 30fps
2. Variance analysis identifying 4–6 candidate controls during 90-second calibration
3. Clean calibration UI showing detected zones highlighted on live video
4. Mapping interface — drag detected motions to 4 action slots
5. Head tilt → smooth proportional mouse cursor movement
6. Dwell detection → left click (600ms dwell threshold)
7. 2 facial gestures → 2 configurable keyboard keys
8. System-level virtual input driver outputting to OS (uinput on Linux for dev, packaged for demo)
9. Demo works in Chrome (browsing) and one web-based game

Everything else — more gesture types, scanning mode, action wheel, Windows/Mac drivers, multi-profile save, cloud sync — is roadmap described in the pitch, not built during the hackathon.

### Team Split (4 people)

| Role | Person | Responsibilities |
|---|---|---|
| **CV Pipeline** | Person 1 | MediaPipe integration, multi-landmark fusion, variance analysis algorithm, calibration logic, dwell detection |
| **System Driver + Input** | Person 2 | Virtual input device (uinput), keyboard/mouse output layer, gesture-to-action mapping engine, latency optimization |
| **Frontend + UX** | Person 3 | Calibration UI, mapping interface, live video overlay with detection visualization, onboarding flow |
| **Demo + Integration** | Person 4 | End-to-end integration, demo environment setup, pitch deck, testing across edge cases, presentation |

### Hour-by-Hour Timeline

| Hours | Milestone |
|---|---|
| 0–4 | MediaPipe pipeline running, landmark data streaming, basic head tilt → raw cursor movement |
| 4–8 | Variance analysis algorithm working, calibration session identifying candidate controls |
| 8–14 | uinput virtual device outputting mouse movement, dwell-to-click working |
| 14–20 | Calibration UI built, live detection overlay rendering correctly |
| 20–26 | Mapping interface complete, gesture-to-keyboard output working for 2 configurable keys |
| 26–32 | Full end-to-end flow working: calibration → mapping → silent background operation |
| 32–38 | Demo hardened — tested in Chrome, tested in web game, edge cases handled |
| 38–42 | Pitch rehearsed, deck finalized, demo machine locked and stable |

### Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| CV backbone | MediaPipe Python (face mesh + pose + hands) | Most accurate real-time landmark detection available, runs on CPU, no GPU required |
| Application layer | Python (FastAPI or Flask for local server) | Fast iteration, rich CV ecosystem, easy process management |
| Virtual input driver | Linux uinput / Windows vJoy + ctypes | System-level output, game-compatible, no per-app configuration needed |
| Frontend | React + WebSocket to local Python server | Clean real-time UI for calibration and mapping, fast to build |
| Demo environment | Arch Linux (native uinput support) | Direct uinput access without additional drivers |

---

## Local Partner

**Memorial Children's Hospital — South Bend, Indiana**

Memorial Children's is a 72-bed pediatric hospital serving northern Indiana and southwestern Michigan. It operates dedicated pediatric oncology, neurology, and rehabilitation units — exactly the populations Axis is built for.

Naming Memorial Children's in the pitch is not decoration. It is a specific, reachable institution 4 miles from Notre Dame's campus where a version of Axis could be piloted within months of the hackathon. Judges will know it. It grounds the project in South Bend's actual community in a way that matters for the Social Impact rubric.

**Secondary partner:** Logan Community Resources (South Bend) — serves adults and children with intellectual and physical disabilities. Provides additional deployment context for the adult SMA, CP, and post-stroke population.

---

## The Pitch — 6-Minute Script

**Minute 0:00–1:00 — Value prop**

Tape a judge's arm to the chair before the presentation starts. Open with:

*"I need you to send an email."*

Let them struggle for 15 seconds. Then:

*"This is what 46 million Americans with motor disabilities experience every day. The solution the medical device industry offers costs six thousand dollars, requires a specialist to set up, and only works inside one proprietary application. We built something different. It runs on the camera you already have. It takes 90 seconds to set up. And once it's running, you just use your computer — like anyone else."*

**Minutes 1:00–5:30 — Live demo**

Open Axis. Run calibration on the taped judge — head and face only. Show the detection UI highlighting their available motions. Map head tilt to mouse, eyebrow raise to click. Let them browse to a website, open a tab, play 30 seconds of a game. Then untape their arm. Let the contrast land.

**Minutes 5:30–6:00 — Close**

*"At Memorial Children's Hospital four miles from here, there are kids who have not seen their friends in two months. Kids who cannot do their own homework, message their own friends, or pause their own Netflix without asking a nurse. Axis gives them that back. Not a special app. Not a special game. Their computer. Their world.*

*This is Axis."*

---

## Why This Wins

The room has eight LLM chatbots with sympathetic angles. Judges are pattern-blind by presentation six. Axis is visually alive from the first second of the demo. It solves a problem every judge will immediately understand — because you put their arm in a sling and made them feel it. It has the strongest social impact story in the room because the population is real, the partner is local, and the need is not hypothetical. And the technical architecture — system-level virtual input from a CV pipeline — is something no other team in that building is doing.

The theme is *"Cultivating a Hopeful Future."*

A kid with cancer who can do her own homework at 2am because nobody built a wall between her and her computer anymore — that is hope. That is the answer to the prompt.

---

*Hesburgh Hackathon 2026 · Team of 4 · 42 hours · Notre Dame, Indiana*
