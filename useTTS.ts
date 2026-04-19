// src/hooks/useTTS.ts
//
// React hook for all ElevenLabs TTS interactions in Axis.
// Handles fetch → Blob → play, WebSocket status feed, and
// interrupting in-progress speech when something more urgent fires.

import { useCallback, useEffect, useRef } from "react";

const API_BASE = "http://localhost:8000/tts";

// ─── Types ──────────────────────────────────────────────────────────────────

export type CalibrationStep =
    | "welcome"
    | "settle"
    | "watching"
    | "halfway"
    | "found_inputs"
    | "confirm"
    | "complete"
    | "no_signal";

export type StatusEvent =
    | "gesture_detected"
    | "gesture_mapped"
    | "click_fired"
    | "scroll_up"
    | "scroll_down"
    | "profile_saved"
    | "profile_loaded"
    | "driver_started"
    | "driver_stopped"
    | "low_confidence"
    | "calibration_needed";

export interface DetectedInput {
    label: string;       // e.g. "head tilt left"
    confidence: number;  // 0.0–1.0
}

// ─── Hook ───────────────────────────────────────────────────────────────────

export function useTTS() {
    const audioRef = useRef<HTMLAudioElement | null>(null);

    // ── Core player ────────────────────────────────────────────────────────

    const playBlob = useCallback((blob: Blob) => {
        // Stop anything currently playing before starting the new clip
        if (audioRef.current) {
            audioRef.current.pause();
            URL.revokeObjectURL(audioRef.current.src);
        }
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.play().catch(() => {
            // Browsers may block autoplay without prior user interaction.
            // In Axis this is fine because the user always triggers the first
            // action via a gesture, satisfying the autoplay policy.
        });
        audio.onended = () => URL.revokeObjectURL(url);
    }, []);

    const fetchAndPlay = useCallback(
        async (endpoint: string, body: object) => {
            try {
                const res = await fetch(`${API_BASE}/${endpoint}`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                });
                if (!res.ok) return;
                const blob = await res.blob();
                playBlob(blob);
            } catch (err) {
                console.warn("[useTTS] fetch failed:", err);
            }
        },
        [playBlob]
    );

    // ── Public API ─────────────────────────────────────────────────────────

    /** Speak arbitrary text (AAC output or one-off messages). */
    const speak = useCallback(
        (text: string) => fetchAndPlay("speak", { text, stream: true }),
        [fetchAndPlay]
    );

    /** Speak a named calibration step. Served from cache after first call. */
    const speakCalibrationStep = useCallback(
        (step: CalibrationStep) =>
            fetchAndPlay("calibration/step", { step }),
        [fetchAndPlay]
    );

    /**
     * Announce the inputs Axis found during calibration.
     * e.g. "I found 4 reliable inputs: head tilt left, eyebrow raise…"
     */
    const speakFoundInputs = useCallback(
        (inputs: DetectedInput[]) =>
            fetchAndPlay("calibration/found-inputs", { inputs }),
        [fetchAndPlay]
    );

    /** Short status chirp — gesture detected, click fired, driver started, etc. */
    const speakStatus = useCallback(
        (event: StatusEvent) => fetchAndPlay("status", { event }),
        [fetchAndPlay]
    );

    /** Confirm a gesture→action mapping. e.g. "Head tilt left mapped to mouse left." */
    const speakMapping = useCallback(
        (gesture: string, action: string) =>
            fetchAndPlay("mapping", { gesture, action }),
        [fetchAndPlay]
    );

    /** AAC: speak text the user composed via gesture-driven input. */
    const speakAAC = useCallback(
        (text: string) => fetchAndPlay("aac", { text }),
        [fetchAndPlay]
    );

    /** Stop whatever is currently playing. */
    const stop = useCallback(() => {
        if (audioRef.current) {
            audioRef.current.pause();
            audioRef.current = null;
        }
    }, []);

    // ── Cleanup on unmount ─────────────────────────────────────────────────

    useEffect(() => () => stop(), [stop]);

    return {
        speak,
        speakCalibrationStep,
        speakFoundInputs,
        speakStatus,
        speakMapping,
        speakAAC,
        stop,
    };
}


// ─── WebSocket status hook ───────────────────────────────────────────────────
//
// Connect this in your gesture driver UI component to get real-time
// audio feedback pushed from the backend as gesture events fire.

export function useTTSStatusSocket() {
    const { playBlob } = useTTSInternal();
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        const ws = new WebSocket("ws://localhost:8000/tts/ws/status");
        wsRef.current = ws;

        ws.binaryType = "arraybuffer";

        ws.onmessage = (e) => {
            if (e.data instanceof ArrayBuffer) {
                const blob = new Blob([e.data], { type: "audio/mpeg" });
                playBlob(blob);
            }
        };

        ws.onerror = (e) => console.warn("[useTTSStatusSocket] WS error:", e);

        return () => ws.close();
    }, [playBlob]);

    /** Send a status event from the frontend (e.g. after gesture engine fires). */
    const emitStatus = useCallback(
        (event: StatusEvent) => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(JSON.stringify({ event }));
            }
        },
        []
    );

    return { emitStatus };
}

// Internal helper so useTTSStatusSocket can share the same playBlob logic
// without duplicating the audioRef pattern.
function useTTSInternal() {
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const playBlob = useCallback((blob: Blob) => {
        if (audioRef.current) {
            audioRef.current.pause();
            URL.revokeObjectURL(audioRef.current.src);
        }
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.play().catch(() => { });
        audio.onended = () => URL.revokeObjectURL(url);
    }, []);
    return { playBlob };
}