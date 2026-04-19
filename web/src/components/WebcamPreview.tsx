// Mirrored webcam preview with live landmark overlay.
//
// The canvas overlay redraws via its own subscription to the MediaPipe hook,
// so neither the parent component nor this one re-renders at frame rate.

import { useEffect, useRef } from "react";
import type { MediaPipeFrame } from "@/hooks/useMediaPipe";
import { IDX } from "@/lib/sources";

const HAND_CONN: [number, number][] = [
  [0, 1],[1, 2],[2, 3],[3, 4],
  [0, 5],[5, 6],[6, 7],[7, 8],
  [5, 9],[9, 10],[10, 11],[11, 12],
  [9, 13],[13, 14],[14, 15],[15, 16],
  [13, 17],[17, 18],[18, 19],[19, 20],
  [0, 17],
];

// Landmarks the detection logic cares about — keep the overlay small and cheap.
const FACE_ACCENT = [
  IDX.NOSE_TIP,
  IDX.UPPER_LIP, IDX.LOWER_LIP,
  IDX.LEFT_EYE_TOP, IDX.LEFT_EYE_BOTTOM, IDX.LEFT_EYE_OUTER, IDX.LEFT_EYE_INNER,
  IDX.RIGHT_EYE_TOP, IDX.RIGHT_EYE_BOTTOM, IDX.RIGHT_EYE_OUTER, IDX.RIGHT_EYE_INNER,
  IDX.LEFT_BROW_TOP, IDX.RIGHT_BROW_TOP,
  IDX.FOREHEAD, IDX.CHIN,
];

interface Props {
  videoRef: React.RefObject<HTMLVideoElement>;
  subscribe?: (cb: (f: MediaPipeFrame) => void) => () => void;
  className?: string;
}

export function WebcamPreview({ videoRef, subscribe, className = "" }: Props) {
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const latestFrame  = useRef<MediaPipeFrame | null>(null);

  // Keep canvas sized to its container (DPR-aware).
  useEffect(() => {
    const c = canvasRef.current;
    const box = containerRef.current;
    if (!c || !box) return;
    const resize = () => {
      const r = box.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      c.width = Math.max(1, Math.floor(r.width * dpr));
      c.height = Math.max(1, Math.floor(r.height * dpr));
      c.style.width = `${r.width}px`;
      c.style.height = `${r.height}px`;
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(box);
    window.addEventListener("resize", resize);
    return () => { ro.disconnect(); window.removeEventListener("resize", resize); };
  }, []);

  // Subscribe to MediaPipe frames + drive the canvas loop. This is independent
  // of React render cycles and runs at native FPS.
  useEffect(() => {
    if (!subscribe) return;
    const unsub = subscribe((frame) => { latestFrame.current = frame; });

    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const c = canvasRef.current;
      if (!c) return;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      const frame = latestFrame.current;
      const w = c.width, h = c.height;
      ctx.clearRect(0, 0, w, h);
      if (!frame) return;

      // mirror to match CSS-flipped video
      const tx = (x: number) => (1 - x) * w;
      const ty = (y: number) => y * h;

      // Face: a handful of accent dots + a glow ring at the nose
      if (frame.faces && frame.faces.length > 0) {
        const lms = frame.faces[0];
        ctx.fillStyle = "#f28b3a";
        for (const idx of FACE_ACCENT) {
          const p = lms[idx];
          if (!p) continue;
          ctx.beginPath();
          ctx.arc(tx(p.x), ty(p.y), 3.2, 0, Math.PI * 2);
          ctx.fill();
        }
        const nose = lms[IDX.NOSE_TIP];
        if (nose) {
          ctx.strokeStyle = "rgba(242,139,58,0.55)";
          ctx.lineWidth = 2.5;
          ctx.beginPath();
          ctx.arc(tx(nose.x), ty(nose.y), 9, 0, Math.PI * 2);
          ctx.stroke();
        }
      }

      // Hands: joints + connecting lines
      if (frame.hands && frame.hands.length > 0) {
        for (const hand of frame.hands) {
          ctx.strokeStyle = "rgba(123,217,138,0.7)";
          ctx.lineWidth = 2;
          for (const [a, b] of HAND_CONN) {
            const pa = hand[a], pb = hand[b];
            if (!pa || !pb) continue;
            ctx.beginPath();
            ctx.moveTo(tx(pa.x), ty(pa.y));
            ctx.lineTo(tx(pb.x), ty(pb.y));
            ctx.stroke();
          }
          ctx.fillStyle = "#7bd98a";
          for (const p of hand) {
            ctx.beginPath();
            ctx.arc(tx(p.x), ty(p.y), 3, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
    };
    raf = requestAnimationFrame(draw);

    return () => {
      unsub();
      cancelAnimationFrame(raf);
      const c = canvasRef.current;
      c?.getContext("2d")?.clearRect(0, 0, c.width, c.height);
    };
  }, [subscribe]);

  return (
    <div
      ref={containerRef}
      className={["relative overflow-hidden rounded-2xl border border-border/70 bg-black/40", className].join(" ")}
    >
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-cover -scale-x-100 bg-black"
        autoPlay
        playsInline
        muted
      />
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full pointer-events-none"
      />
      <div className="absolute inset-0 pointer-events-none rounded-2xl ring-1 ring-white/5" />
    </div>
  );
}
