// Practice — guided tutorial that teaches the user their own bindings.
// Each step shows a mini-goal (hit a target, click it, etc.) and uses
// real-time capability detection to validate.

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shell, StepDots } from "@/components/Shell";
import { WebcamPreview } from "@/components/WebcamPreview";
import { useMediaPipe } from "@/hooks/useMediaPipe";
import { useProfile } from "@/state/profile";
import {
  eyeAspectRatio, eyebrowRaise, mouthRatio, noseTip,
} from "@/lib/sources";
import { launchRuntime } from "@/lib/api";

interface Step {
  key: string;
  title: string;
  prompt: string;
  exercise: "cursor" | "click";
  // Which capability each step exercises (for the gating copy).
  source: string;
}

function buildSteps(bindings: { source: string; action: string; enabled: boolean }[]): Step[] {
  const out: Step[] = [];
  const cursorB = bindings.find((b) => b.enabled && b.action === "cursor_xy");
  if (cursorB) {
    const label = cursorB.source === "nose" ? "head" : "finger";
    out.push({
      key: "cursor",
      title: `Move the cursor with your ${label}`,
      prompt: `Move your ${label} to follow the glowing target.`,
      exercise: "cursor",
      source: cursorB.source,
    });
  }
  const clickB = bindings.find((b) =>
    b.enabled && (b.action === "left_press" || b.action === "left_click"));
  if (clickB) {
    const label = { mouth: "mouth", blink: "blink", brow: "eyebrows" }[clickB.source] ?? clickB.source;
    out.push({
      key: "click",
      title: `Click with your ${label}`,
      prompt: clickB.action === "left_press"
        ? `Open your ${label} and hold it to click. Release to stop.`
        : `${label[0].toUpperCase() + label.slice(1)} to click the target when it's under your cursor.`,
      exercise: "click",
      source: clickB.source,
    });
  }
  return out;
}

export default function Practice() {
  const nav = useNavigate();
  const { bindings } = useProfile();
  const mp = useMediaPipe();

  const steps = useMemo(() => buildSteps(bindings), [bindings]);
  const [stepIdx, setStepIdx] = useState(0);
  const step = steps[stepIdx];

  // Shared cursor state (browser-space; just a demo cursor, doesn't drive OS)
  const [cursor, setCursor] = useState<{ x: number; y: number }>({ x: 0.5, y: 0.5 });
  const [isClicking, setIsClicking] = useState(false);
  const [score, setScore] = useState(0);       // targets completed this step
  const targetRef = useRef<{ x: number; y: number } | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  // Random target helper
  function newTarget() {
    targetRef.current = {
      x: 0.15 + Math.random() * 0.7,
      y: 0.2 + Math.random() * 0.6,
    };
  }
  useEffect(() => { newTarget(); setScore(0); }, [stepIdx]);

  // Per-frame: update cursor pos (from nose/finger) and click (from mouth/blink/brow)
  useEffect(() => {
    if (!step) return;
    const unsub = mp.subscribe((frame) => {
      // Cursor source
      if (step.exercise === "cursor" || step.exercise === "click") {
        const cursorSource = bindings.find((b) => b.enabled && b.action === "cursor_xy");
        if (cursorSource) {
          const pt = cursorSource.source === "nose"
            ? noseTip(frame.faces)
            : cursorSource.source === "index_tip"
              ? (() => {
                  if (!frame.hands || frame.hands.length === 0) return null;
                  const tip = frame.hands[0][8];
                  return [tip.x, tip.y] as [number, number];
                })()
              : null;
          if (pt) {
            // mirror x to match webcam preview
            setCursor({ x: 1 - pt[0], y: pt[1] });
          }
        }
      }

      // Click source
      if (step.exercise === "click") {
        const clickB = bindings.find((b) =>
          b.enabled && (b.action === "left_press" || b.action === "left_click"));
        if (clickB) {
          let pressed = false;
          if (clickB.source === "mouth") {
            const v = mouthRatio(frame.faces);
            pressed = v !== null && v > 0.09;
          } else if (clickB.source === "blink") {
            const ear = eyeAspectRatio(frame.faces, "both");
            pressed = ear !== null && ear < 0.18;
          } else if (clickB.source === "brow") {
            const v = eyebrowRaise(frame.faces);
            pressed = v !== null && v > 0.06;
          }
          setIsClicking(pressed);
        }
      }
    });
    return unsub;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mp.ready, step?.key]);

  // Goal detection — hover near target for cursor exercise, hover + click for click exercise
  const hoverTRef = useRef(0);
  useEffect(() => {
    if (!step || !targetRef.current) return;
    const stage = stageRef.current;
    if (!stage) return;
    const t = targetRef.current;
    const dx = cursor.x - t.x;
    const dy = cursor.y - t.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const hovering = dist < 0.07;

    if (step.exercise === "cursor") {
      if (hovering) {
        hoverTRef.current += 1 / 60;
        if (hoverTRef.current > 0.9) {
          setScore((s) => s + 1);
          newTarget();
          hoverTRef.current = 0;
        }
      } else {
        hoverTRef.current = Math.max(0, hoverTRef.current - 0.05);
      }
    } else if (step.exercise === "click") {
      if (hovering && isClicking) {
        setScore((s) => s + 1);
        newTarget();
      }
    }
  }, [cursor, isClicking, step]);

  // Advance after reaching a few targets per step
  useEffect(() => {
    if (score >= 3 && step) {
      if (stepIdx + 1 >= steps.length) {
        // Done — launch runtime and go to Done screen.
        launchRuntime().catch(() => {});
        nav("/done");
      } else {
        setStepIdx((n) => n + 1);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [score]);

  if (steps.length === 0) {
    return (
      <Shell>
        <div className="max-w-2xl mx-auto text-center pt-24">
          <h1 className="text-3xl font-semibold">Nothing to practice yet</h1>
          <p className="text-muted mt-3">Run setup first to get a mapping.</p>
          <button className="btn btn-primary mt-8" onClick={() => nav("/")}>Go to setup</button>
        </div>
      </Shell>
    );
  }

  const t = targetRef.current;

  return (
    <Shell>
      <div className="max-w-5xl mx-auto">
        <StepDots total={steps.length} current={stepIdx} />

        <div className="grid grid-cols-1 md:grid-cols-[1.4fr_1fr] gap-8 mt-8">
          <div className="card p-8 min-h-[500px] flex flex-col">
            <div className="text-xs uppercase tracking-[0.2em] text-ember font-medium">
              Practice {stepIdx + 1} of {steps.length}
            </div>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight">{step.title}</h2>
            <p className="mt-2 text-muted">{step.prompt}</p>

            <div
              ref={stageRef}
              className="relative mt-6 flex-1 rounded-xl bg-black/30 border border-border/50 overflow-hidden"
            >
              {t && (
                <div
                  className={
                    "absolute rounded-full border-2 " +
                    (step.exercise === "click" ? "border-ember" : "border-ok") +
                    " shadow-glow animate-pulse-soft"
                  }
                  style={{
                    left: `calc(${t.x * 100}% - 22px)`,
                    top:  `calc(${t.y * 100}% - 22px)`,
                    width: 44,
                    height: 44,
                  }}
                />
              )}
              <div
                className={
                  "absolute h-5 w-5 rounded-full transition-transform " +
                  (isClicking ? "bg-ok shadow-glow scale-110" : "bg-ember")
                }
                style={{
                  left: `calc(${cursor.x * 100}% - 10px)`,
                  top:  `calc(${cursor.y * 100}% - 10px)`,
                }}
              />
            </div>

            <div className="flex items-center justify-between mt-6 text-sm">
              <span className="text-muted">Targets hit: <span className="text-text font-medium">{score} / 3</span></span>
              <button className="btn btn-ghost text-xs" onClick={() => setScore(3)}>Skip</button>
            </div>
          </div>

          <div className="space-y-4">
            <WebcamPreview videoRef={mp.videoRef} subscribe={mp.subscribe} className="aspect-[4/3]" />
            <div className="card p-4 text-sm">
              <div className="text-xs uppercase tracking-wide text-muted mb-2">how it's working</div>
              <ul className="space-y-1.5">
                {bindings.filter((b) => b.enabled).map((b, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-ember" />
                    <span className="text-text">{b.source} → {b.action}</span>
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
