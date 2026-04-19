// src/hooks/useTTS.ts
//
// React hook for all ElevenLabs TTS interactions in Axis.
// Handles fetch → Blob → play, WebSocket status feed, and
// interrupting in-progress speech when something more urgent fires.

import { useCallback, useEffect, useRef } from "react";

const API_BASE = "http://localhost:8000/tts";

// ─── Shared audio singleton ──────────────────────────────────────────────────
//
// Module-level so both useTTS() and useTTSStatusSocket() share one audio
// context. Calling stop() from either hook cancels audio from the other,
// and there is never more than one clip playing at a time.

let _currentAudio: HTMLAudioElement | null = null;
let _currentUrl: string | null = null;

function _playBlob(blob: Blob): void {
    // Stop and release whatever is currently playing
    if (_currentAudio) {
        _currentAudio.pause();
        _currentAudio = null;
    }
    if (_currentUrl) {
        URL.revokeObjectURL(_currentUrl);
        _currentUrl = null;
    }

    const url = URL.createObjectURL(blob);
    _currentUrl = url;
    const audio = new Audio(url);
    _currentAudio = audio;

    audio.play().catch(() => {
        // Browsers may block autoplay without prior user interaction.
        // In Axis this is fine — the user's first gesture satisfies the policy.
    });
    audio.onended = () => {
        URL.revokeObjectURL(url);
        if (_currentUrl === url) _currentUrl = null;
        if (_currentAudio === audio) _currentAudio = null;
    };
}

function _stopAudio(): void {
    if (_currentAudio) {
        _currentAudio.pause();
        _currentAudio = null;
    }
    if (_currentUrl) {
        URL.revokeObjectURL(_currentUrl);
        _currentUrl = null;
    }
}

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
                _playBlob(blob);
            } catch (err) {
                console.warn("[useTTS] fetch failed:", err);
            }
        },
        []
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

    /** Stop whatever is currently playing and release the blob URL. */
    const stop = useCallback(() => _stopAudio(), []);

    useEffect(() => () => _stopAudio(), []);

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
// Uses the same shared audio singleton as useTTS() — stop() from either
// hook cancels audio from the other.

export function useTTSStatusSocket() {
    const wsRef = useRef<WebSocket | null>(null);

    useEffect(() => {
        const ws = new WebSocket("ws://localhost:8000/tts/ws/status");
        wsRef.current = ws;
        ws.binaryType = "arraybuffer";

        ws.onmessage = (e) => {
            if (e.data instanceof ArrayBuffer) {
                _playBlob(new Blob([e.data], { type: "audio/mpeg" }));
            }
        };

        ws.onerror = (e) => console.warn("[useTTSStatusSocket] WS error:", e);

        return () => ws.close();
    }, []);

    /** Send a status event from the frontend (e.g. after gesture engine fires). */
    const emitStatus = useCallback((event: StatusEvent) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ event }));
        }
    }, []);

    return { emitStatus };
}