"""
voice/narrate.py

ScreenNarrator — reads the current screen state aloud.

Three layers of text extraction (richest to simplest):
  1. AT-SPI focused element (pyatspi — richest, optional dependency)
  2. Primary selection (xclip — whatever the user has highlighted)
  3. Active window title (xdotool — always available on X11)

Continuous narration mode polls every AXIS_NARRATION_INTERVAL seconds
and speaks when the screen content changes.

apt install xdotool xclip        (or pacman -S xdotool xclip on Arch)
pip install pyatspi               (optional, for AT-SPI support)
"""

import asyncio
import os
from typing import Callable, Optional

try:
    import pyatspi
    _ATSPI_AVAILABLE = True
except ImportError:
    _ATSPI_AVAILABLE = False

_POLL_INTERVAL = float(os.getenv("AXIS_NARRATION_INTERVAL", "2.5"))


class ScreenNarrator:
    """
    Extracts text from the current screen state and voices it.

    speak_fn: synchronous callable that takes a string and speaks it.
    In VoiceBridge this is wired to the existing tts/service.py pipeline.
    """

    def __init__(self, speak_fn: Callable[[str], None]):
        self._speak   = speak_fn
        self._running = False
        self._last    = ""

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_screen_context(self) -> str:
        """
        Returns a human-readable string describing what is on screen.
        Called by ActionDispatcher._tool_narrate_screen() and the continuous loop.
        """
        parts: list[str] = []

        title = await _get_window_title()
        if title:
            parts.append(f"Window: {title}")

        selection = await _get_selection()
        if selection:
            parts.append(f"Selected: {selection[:200]}")

        if _ATSPI_AVAILABLE:
            focused = await _get_atspi_focused_text()
            if focused and focused != title:
                parts.append(f"Focused: {focused[:200]}")

        return " | ".join(parts)

    async def narrate_once(self) -> str:
        """Read the screen aloud once. Returns the text spoken."""
        text = await self.get_screen_context()
        if text:
            self._speak(text)
        return text

    async def start_continuous(self) -> None:
        """
        Poll the screen and narrate whenever the content changes.
        Runs until stop() is called. Designed to run as an asyncio Task.
        """
        self._running = True
        print("[Narrate] Continuous narration started.")
        while self._running:
            try:
                text = await self.get_screen_context()
                if text and text != self._last:
                    self._speak(text)
                    self._last = text
            except Exception as exc:
                print(f"[Narrate] Error: {exc}")
            await asyncio.sleep(_POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False
        print("[Narrate] Continuous narration stopped.")


# ── System helpers ────────────────────────────────────────────────────────────

async def _get_window_title() -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "getactivewindow", "getwindowname",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2)
        return stdout.decode().strip()
    except Exception:
        return ""


async def _get_selection() -> str:
    """Return currently selected (highlighted) text via xclip."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "xclip", "-o", "-selection", "primary",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=1)
        text = stdout.decode().strip()
        return (text[:500] + "...") if len(text) > 500 else text
    except Exception:
        return ""


async def _get_atspi_focused_text() -> str:
    """Return text from the AT-SPI accessible element that currently has focus."""
    if not _ATSPI_AVAILABLE:
        return ""
    try:
        desktop = pyatspi.Registry.getDesktop(0)
        for app in desktop:
            if app is None:
                continue
            for window in app:
                found = _find_focused(window)
                if found:
                    iface = found.queryText()
                    return iface.getText(0, iface.characterCount)
    except Exception:
        pass
    return ""


def _find_focused(obj) -> Optional[object]:
    if obj is None:
        return None
    try:
        if obj.getState().contains(pyatspi.STATE_FOCUSED):
            return obj
        for child in obj:
            result = _find_focused(child)
            if result:
                return result
    except Exception:
        pass
    return None