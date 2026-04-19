"""HalfDuplexAudioInterface -- mutes the microphone while the agent is
speaking so the agent cannot respond to its own TTS.

Defense layers:
  1. _speaking flag + output-queue depth gate. While audio is still queued
     for the speaker, the mic feeds silence regardless of wall clock.
  2. Tail window. After the last speaker write, continue muting for
     EMBER_SPEAK_TAIL_S seconds so speaker reverb + room echo decay.
  3. interrupt() clears both — ElevenLabs calls it when the user barges in.

Tuning: EMBER_SPEAK_TAIL_S (default 0.5s). Bump to 1.5-2.5 on loud speakers
in echoey rooms where the agent still hears itself; drop lower only if users
complain they can't interrupt fast enough.
"""

from __future__ import annotations

import os
import queue
import threading
import time

from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class HalfDuplexAudioInterface(DefaultAudioInterface):

    SPEAK_TAIL_S = _env_float("EMBER_SPEAK_TAIL_S", 1.0)

    def __init__(self) -> None:
        super().__init__()
        self._speaking = threading.Event()
        self._last_out_ts = 0.0

    def output(self, audio: bytes) -> None:
        # Mark the speaking window immediately when a chunk is enqueued.
        self._speaking.set()
        self._last_out_ts = time.monotonic()
        super().output(audio)

    def interrupt(self) -> None:
        super().interrupt()
        self._speaking.clear()
        # Drain any queued chunks so a barge-in actually stops playback.
        try:
            while True:
                self.output_queue.get_nowait()
        except Exception:
            pass

    def _output_thread(self):
        """Same as base but stamp _last_out_ts AFTER the speaker write so
        the tail window extends from real playback, not queueing."""
        while not self.should_stop.is_set():
            try:
                audio = self.output_queue.get(timeout=0.25)
                self.out_stream.write(audio)
                self._last_out_ts = time.monotonic()
                self._speaking.set()
            except queue.Empty:
                pass

    def _in_callback(self, in_data, frame_count, time_info, status):
        now = time.monotonic()

        # Hard gate: any audio still queued for playback means we're about
        # to hear ourselves — mute input regardless of tail timing.
        pending = self.output_queue.qsize() > 0

        if self._speaking.is_set() or pending:
            if pending or (now - self._last_out_ts) < self.SPEAK_TAIL_S:
                silent = b"\x00" * len(in_data)
                if self.input_callback:
                    self.input_callback(silent)
                return (None, self.pyaudio.paContinue)
            self._speaking.clear()

        if self.input_callback:
            self.input_callback(in_data)
        return (None, self.pyaudio.paContinue)
