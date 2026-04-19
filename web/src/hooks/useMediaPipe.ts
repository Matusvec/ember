// useMediaPipe — single source of truth for face + hand landmarks.
//
// IMPORTANT: frames arrive at ~60 Hz. We do NOT store them in React state,
// because that forces every consumer to re-render 60×/s and tanks the UI.
// Consumers read the latest via `getLatest()` or `subscribe()` and push
// updates into their own 5–10 Hz render cycle.

import { useEffect, useRef, useState } from "react";
import {
  FilesetResolver,
  FaceLandmarker,
  HandLandmarker,
  type NormalizedLandmark,
} from "@mediapipe/tasks-vision";

export interface MediaPipeFrame {
  faces: NormalizedLandmark[][] | undefined;
  hands: NormalizedLandmark[][] | undefined;
  timestamp: number;
}

export type MediaPipePhase = "init" | "camera" | "models" | "ready" | "error";

const WASM_BASE  = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.16/wasm";
const FACE_MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const HAND_MODEL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

export interface UseMediaPipeResult {
  phase: MediaPipePhase;
  ready: boolean;
  error: string | null;
  videoRef: React.RefObject<HTMLVideoElement>;
  getLatest: () => MediaPipeFrame | null;
  subscribe: (cb: (f: MediaPipeFrame) => void) => () => void;
}

export function useMediaPipe(): UseMediaPipeResult {
  const videoRef  = useRef<HTMLVideoElement>(null);
  const latestRef = useRef<MediaPipeFrame | null>(null);
  const subsRef   = useRef<Set<(f: MediaPipeFrame) => void>>(new Set());
  const rafRef    = useRef<number | null>(null);
  const faceRef   = useRef<FaceLandmarker | null>(null);
  const handRef   = useRef<HandLandmarker | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [phase, setPhase] = useState<MediaPipePhase>("init");
  const [error, setError] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);

  // Attach the stream to the video element declaratively whenever either
  // changes. This is more reliable than imperatively assigning from inside
  // the async boot sequence.
  useEffect(() => {
    const v = videoRef.current;
    if (!v || !stream) return;
    v.srcObject = stream;
    v.muted = true;
    v.playsInline = true;
    v.play().catch(() => { /* autoplay handles it */ });
  }, [stream]);

  useEffect(() => {
    let mounted = true;

    (async () => {
      try {
        // 1. Camera first, so the user sees themselves even if models are slow.
        setPhase("camera");
        const s = await navigator.mediaDevices.getUserMedia({
          video: { width: 640, height: 480, facingMode: "user" },
          audio: false,
        });
        if (!mounted) { s.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = s;
        setStream(s);

        // Wait for a ready video element.
        for (let i = 0; i < 200 && mounted; i++) {
          const v = videoRef.current;
          if (v && v.readyState >= 2 && v.videoWidth > 0) break;
          await new Promise((r) => setTimeout(r, 25));
        }
        if (!mounted) return;

        // 2. Boot MediaPipe.
        setPhase("models");
        const vision = await FilesetResolver.forVisionTasks(WASM_BASE);
        if (!mounted) return;

        const mkFace = (d: "GPU" | "CPU") => FaceLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: FACE_MODEL, delegate: d },
          runningMode: "VIDEO",
          numFaces: 1,
        });
        const mkHand = (d: "GPU" | "CPU") => HandLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: HAND_MODEL, delegate: d },
          runningMode: "VIDEO",
          numHands: 1,
        });

        const face = await mkFace("GPU").catch((e) => {
          console.warn("[useMediaPipe] face GPU failed, falling back to CPU", e);
          return mkFace("CPU");
        });
        if (!mounted) { face.close(); return; }
        faceRef.current = face;

        const hand = await mkHand("GPU").catch((e) => {
          console.warn("[useMediaPipe] hand GPU failed, falling back to CPU", e);
          return mkHand("CPU");
        });
        if (!mounted) { hand.close(); return; }
        handRef.current = hand;

        setPhase("ready");
        console.log("[useMediaPipe] ready");

        // 3. RAF loop — never calls setState in the hot path.
        let lastTs = -1;
        let frameCount = 0;
        let firstFaceLogged = false;
        const loop = () => {
          if (!mounted) return;
          const vid = videoRef.current;
          const f = faceRef.current;
          const h = handRef.current;
          if (vid && f && h) {
            const ts = performance.now();
            if (ts > lastTs && vid.readyState >= 2 && vid.videoWidth > 0) {
              lastTs = ts;
              frameCount++;
              try {
                const fr = f.detectForVideo(vid, ts);
                const hr = h.detectForVideo(vid, ts);
                const snap: MediaPipeFrame = {
                  faces: fr.faceLandmarks,
                  hands: hr.landmarks,
                  timestamp: ts / 1000,
                };
                latestRef.current = snap;
                subsRef.current.forEach((cb) => cb(snap));
                if (!firstFaceLogged && fr.faceLandmarks && fr.faceLandmarks.length > 0) {
                  firstFaceLogged = true;
                  console.log(
                    `[useMediaPipe] first face detected at frame=${frameCount} video=${vid.videoWidth}x${vid.videoHeight}`
                  );
                }
              } catch (e) {
                if (frameCount < 3) console.warn("[useMediaPipe] detect error", e);
              }
            }
          }
          rafRef.current = requestAnimationFrame(loop);
        };
        rafRef.current = requestAnimationFrame(loop);
      } catch (err: any) {
        console.error("[useMediaPipe] init failed:", err);
        setError(err?.message ?? String(err));
        setPhase("error");
      }
    })();

    return () => {
      mounted = false;
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      try { faceRef.current?.close(); } catch {}
      try { handRef.current?.close(); } catch {}
      streamRef.current?.getTracks().forEach((t) => t.stop());
      faceRef.current = null;
      handRef.current = null;
      streamRef.current = null;
      latestRef.current = null;
    };
  }, []);

  return {
    phase,
    ready: phase === "ready",
    error,
    videoRef,
    getLatest: () => latestRef.current,
    subscribe: (cb) => {
      subsRef.current.add(cb);
      return () => { subsRef.current.delete(cb); };
    },
  };
}
