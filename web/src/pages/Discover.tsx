// Capability discovery — walks the user through 7 tests using browser-side
// MediaPipe. Each test has a live meter and auto-advances on detection.
//
// Per-frame detection runs at 60 Hz via subscribe() into REFS — we never
// setState in the hot path. A 10 Hz heartbeat drives React re-renders so the
// UI stays responsive without flooding the reconciler.

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shell, StepDots } from "@/components/Shell";
import { WebcamPreview } from "@/components/WebcamPreview";
import { Meter, ProgressPill } from "@/components/Meter";
import { useMediaPipe } from "@/hooks/useMediaPipe";
import { useProfile } from "@/state/profile";
import {
  eyeAspectRatio, eyebrowRaise, mouthRatio, noseTip,
} from "@/lib/sources";
import type { CapabilityId } from "@/lib/types";

interface Test {
  id: CapabilityId;
  title: string;
  hint: string;
  meter: string;
  maxValue: number;
}

const TESTS: Test[] = [
  { id: "head",     title: "Try moving your head",     hint: "Tilt, nod, or shift side to side — anything that moves",     meter: "head motion range", maxValue: 0.12 },
  { id: "mouth",    title: "Try opening your mouth",   hint: "Open it wide once — like saying \"ah\"",                       meter: "mouth opening",     maxValue: 0.25 },
  { id: "blink",    title: "Try blinking both eyes",   hint: "A firm, deliberate blink — close for a beat, then open",      meter: "eye closure",       maxValue: 0.25 },
  { id: "brow",     title: "Try raising your eyebrows",hint: "Lift your brows like you're surprised",                       meter: "brow lift",         maxValue: 0.04 },
  { id: "hand",     title: "Try holding up your hand", hint: "Put your hand into the camera view",                          meter: "hand in frame",     maxValue: 1.0 },
  { id: "voice",    title: "Try speaking any words",   hint: "Say hi, count to three, anything",                            meter: "mic input",         maxValue: 0.15 },
  { id: "keyboard", title: "Try pressing any key",     hint: "Any letter or number (Space will skip)",                      meter: "key pressed",       maxValue: 1.0 },
];

const TEST_DURATION = 8.0;
const LINGER_AFTER_DETECT = 2.0;

interface DetectionBuffer {
  detected: boolean;
  value: number;
  enteredAt: number;
  noseXs: number[]; noseYs: number[];
  blinkPrevClosed: boolean; blinkCount: number;
  browBaseline: number | null; browSum: number; browN: number;
  handFrames: number; totalFrames: number;
  micPeak: number;
  keyPressed: boolean;
}

function freshBuffer(now: number): DetectionBuffer {
  return {
    detected: false, value: 0, enteredAt: now,
    noseXs: [], noseYs: [],
    blinkPrevClosed: false, blinkCount: 0,
    browBaseline: null, browSum: 0, browN: 0,
    handFrames: 0, totalFrames: 0,
    micPeak: 0, keyPressed: false,
  };
}

export default function Discover() {
  const nav = useNavigate();
  const { caps, setCap } = useProfile();
  const mp = useMediaPipe();

  const [idx, setIdx] = useState(0);
  const idxRef = useRef(0);
  idxRef.current = idx;

  // Mutable detection buffer (written at 60 Hz).
  const bufRef = useRef<DetectionBuffer>(freshBuffer(performance.now() / 1000));
  // UI snapshot (read at 10 Hz into React state so components re-render).
  const [ui, setUi] = useState<{ value: number; detected: boolean; elapsed: number }>(
    { value: 0, detected: false, elapsed: 0 }
  );

  const micRmsRef = useRef<number>(0);
  const micStreamRef = useRef<MediaStream | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);

  const test = TESTS[idx];

  // Reset detection buffer whenever the test changes.
  useEffect(() => {
    bufRef.current = freshBuffer(performance.now() / 1000);
    setUi({ value: 0, detected: false, elapsed: 0 });
  }, [idx]);

  // ---- Keyboard (global) ----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { nav("/"); return; }
      if (e.key === " ") { advance(false); return; }
      if (TESTS[idxRef.current].id === "keyboard" && e.key.length === 1) {
        bufRef.current.keyPressed = true;
        bufRef.current.detected = true;
        bufRef.current.value = 1;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- Mic (voice test only) ----
  useEffect(() => {
    if (test.id !== "voice") return;
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        micStreamRef.current = stream;
        const ctx = new AudioContext();
        micCtxRef.current = ctx;
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        src.connect(analyser);
        const buf = new Float32Array(analyser.fftSize);
        const tick = () => {
          if (cancelled) return;
          analyser.getFloatTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
          micRmsRef.current = Math.sqrt(sum / buf.length);
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      } catch { /* no mic — stays false */ }
    })();
    return () => {
      cancelled = true;
      micStreamRef.current?.getTracks().forEach((t) => t.stop());
      micStreamRef.current = null;
      micCtxRef.current?.close().catch(() => {});
      micCtxRef.current = null;
      micRmsRef.current = 0;
    };
  }, [test.id]);

  // ---- MediaPipe subscription: pure refs, no setState ----
  useEffect(() => {
    const unsub = mp.subscribe((frame) => {
      const buf = bufRef.current;
      const id = TESTS[idxRef.current].id;
      buf.totalFrames += 1;

      if (id === "head") {
        const tip = noseTip(frame.faces);
        if (tip) {
          buf.noseXs.push(tip[0]);
          buf.noseYs.push(tip[1]);
          if (buf.noseXs.length > 60) { buf.noseXs.shift(); buf.noseYs.shift(); }
          if (buf.noseXs.length >= 10) {
            const rx = Math.max(...buf.noseXs) - Math.min(...buf.noseXs);
            const ry = Math.max(...buf.noseYs) - Math.min(...buf.noseYs);
            const rng = Math.max(rx, ry);
            buf.value = rng;
            if (rng > 0.05) buf.detected = true;
          }
        }
      } else if (id === "mouth") {
        const v = mouthRatio(frame.faces);
        if (v !== null) {
          buf.value = v;
          if (v > 0.09) buf.detected = true;
        }
      } else if (id === "blink") {
        const ear = eyeAspectRatio(frame.faces, "both");
        if (ear !== null) {
          buf.value = Math.max(0, 0.3 - ear);
          const closed = ear < 0.17;
          if (closed && !buf.blinkPrevClosed) buf.blinkCount += 1;
          buf.blinkPrevClosed = closed;
          if (buf.blinkCount >= 1) buf.detected = true;
        }
      } else if (id === "brow") {
        const v = eyebrowRaise(frame.faces);
        if (v !== null) {
          buf.browSum += v; buf.browN += 1;
          const elapsed = frame.timestamp - buf.enteredAt;
          if (buf.browBaseline === null && elapsed > 0.8 && buf.browN > 5) {
            buf.browBaseline = buf.browSum / buf.browN;
          }
          if (buf.browBaseline !== null) {
            const d = v - buf.browBaseline;
            buf.value = Math.max(0, d);
            if (d > 0.012) buf.detected = true;
          }
        }
      } else if (id === "hand") {
        if (frame.hands && frame.hands.length > 0) buf.handFrames += 1;
        const ratio = buf.handFrames / Math.max(1, buf.totalFrames);
        buf.value = ratio;
        if (ratio > 0.25 && buf.totalFrames > 20) buf.detected = true;
      } else if (id === "voice") {
        const peak = Math.max(buf.micPeak, micRmsRef.current);
        buf.micPeak = peak;
        buf.value = peak;
        if (peak > 0.02) buf.detected = true;
      } else if (id === "keyboard") {
        buf.value = buf.keyPressed ? 1 : 0;
      }
    });
    return unsub;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- 10 Hz heartbeat: pulls ref state → React state → advances timer ----
  useEffect(() => {
    const i = setInterval(() => {
      const buf = bufRef.current;
      const now = performance.now() / 1000;
      const elapsed = now - buf.enteredAt;
      setUi({ value: buf.value, detected: buf.detected, elapsed });

      if (elapsed >= TEST_DURATION) advance(buf.detected);
      else if (buf.detected && elapsed >= LINGER_AFTER_DETECT) advance(true);
    }, 100);
    return () => clearInterval(i);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx]);

  function advance(detected: boolean) {
    setCap(TESTS[idxRef.current].id, detected);
    if (idxRef.current + 1 >= TESTS.length) {
      nav("/configure");
      return;
    }
    setIdx((n) => n + 1);
  }

  const progress = Math.min(1, ui.elapsed / TEST_DURATION);
  const statusLabel = mp.error ? mp.error
    : mp.phase === "camera" ? "starting camera..."
    : mp.phase === "models" ? "loading tracker..."
    : mp.phase === "ready"  ? "camera live" : "initializing...";

  return (
    <Shell>
      <div className="max-w-5xl mx-auto">
        <StepDots total={TESTS.length} current={idx} />

        <div className="grid grid-cols-1 md:grid-cols-[1.4fr_1fr] gap-8 mt-8 items-start">
          <div className="card p-10 min-h-[430px] flex flex-col">
            <div className="text-xs uppercase tracking-[0.2em] text-ember font-medium">
              Step {idx + 1} of {TESTS.length}
            </div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight">{test.title}</h2>
            <p className="mt-2 text-muted">{test.hint}</p>

            <div className="mt-10 space-y-8">
              <div>
                <div className="flex justify-between text-xs uppercase tracking-wide text-dim mb-2">
                  <span>time left</span>
                  <span>{Math.max(0, TEST_DURATION - ui.elapsed).toFixed(1)}s</span>
                </div>
                <ProgressPill progress={1 - progress} tone="ember" />
              </div>
              <div>
                <div className="flex justify-between text-xs uppercase tracking-wide text-dim mb-2">
                  <span>{test.meter}</span>
                  <span>{ui.detected ? "detected" : "listening…"}</span>
                </div>
                <Meter value={ui.value} max={test.maxValue} active={ui.detected} />
              </div>
            </div>

            <div className="flex items-center justify-between mt-auto pt-10">
              <span className={
                "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-sm " +
                (ui.detected ? "bg-ok/15 text-ok" : "bg-card/60 text-muted border border-border/60")
              }>
                <span className={"h-2 w-2 rounded-full " + (ui.detected ? "bg-ok" : "bg-ember animate-pulse-soft")} />
                {ui.detected ? "great, got it" : "waiting..."}
              </span>
              <div className="flex items-center gap-2 text-xs text-dim">
                <kbd className="chip">space</kbd> skip
                <kbd className="chip">esc</kbd> quit
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <WebcamPreview videoRef={mp.videoRef} subscribe={mp.subscribe} className="aspect-[4/3]" />
            <div className="text-xs text-dim text-center">
              <span className={mp.error ? "text-warn" : ""}>{statusLabel}</span>
            </div>
            <div className="card p-4">
              <div className="text-xs uppercase tracking-wide text-muted mb-2">detected so far</div>
              <ul className="space-y-1.5 text-sm">
                {TESTS.map((t, i) => (
                  <li key={t.id} className="flex items-center gap-2">
                    <span className={
                      "h-2 w-2 rounded-full " +
                      (i === idx ? "bg-ember"
                        : (caps as any)[t.id] ? "bg-ok"
                        : i < idx ? "bg-border" : "bg-border/40")
                    } />
                    <span className={
                      (caps as any)[t.id] ? "text-text" : i < idx ? "text-dim" : "text-muted"
                    }>
                      {t.title.replace("Try ", "")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
