"""
tools/actions.py

ActionDispatcher — the single shared boundary between the CV pipeline
and the voice pipeline. Both layers call execute() here; this module
turns the call into virtual mouse / keyboard events.

Responsibilities:
  - Execute tool calls coming from ElevenLabs ConvAI
  - Maintain an undo stack (last 20 reversible actions)
  - Expose TOOL_SCHEMAS for the ElevenLabs agent override config

Swapping in the matus VirtualMouse:
    dispatcher = ActionDispatcher(virtual_input=matus_virtual_mouse)
Without it, falls back to pyautogui (fine for testing and Linux demos).

pip install pyautogui
"""

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import urllib.parse
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional

# pyautogui may fail to import on Wayland (tries to connect to X11 at module load).
# Guard it so the voice pipeline can still be wired to the matus VirtualMouse without
# pyautogui being functional.  Every call site below checks _HAS_PYAUTOGUI first.
try:
    import pyautogui  # type: ignore
    pyautogui.FAILSAFE = False
    _HAS_PYAUTOGUI = True
except Exception as _pyag_exc:  # pragma: no cover
    pyautogui = None  # type: ignore
    _HAS_PYAUTOGUI = False
    _PYAUTOGUI_IMPORT_ERROR = _pyag_exc


# ─── Tool schemas (ElevenLabs Conversational AI client tool format) ──────────

TOOL_SCHEMAS = [
    {
        "type": "client",
        "name": "move_cursor",
        "description": "Move the mouse cursor to a named screen region.",
        "parameters": {
            "type": "object",
            "required": ["region"],
            "properties": {
                "region": {
                    "type": "string",
                    "enum": [
                        "top-left", "top-center", "top-right",
                        "middle-left", "middle", "middle-right",
                        "bottom-left", "bottom-center", "bottom-right",
                    ],
                }
            },
        },
    },
    {
        "type": "client",
        "name": "click",
        "description": "Fire a mouse click at the current cursor position.",
        "parameters": {
            "type": "object",
            "properties": {
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                }
            },
        },
    },
    {
        "type": "client",
        "name": "scroll",
        "description": "Scroll the active window up or down.",
        "parameters": {
            "type": "object",
            "required": ["direction"],
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down"]},
                "amount":    {"type": "integer", "default": 3},
            },
        },
    },
    {
        "type": "client",
        "name": "type_text",
        "description": "Type literal text via the virtual keyboard.",
        "parameters": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
    },
    {
        "type": "client",
        "name": "launch_app",
        "description": "Open an application by name (Chrome, Firefox, Slack, etc). Falls back to xdg-open for anything not in the known list.",
        "parameters": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
    },
    {
        "type": "client",
        "name": "search_web",
        "description": "Open the default browser to a search results page for a query. Use this for 'search for X', 'look up X', 'google X'.",
        "parameters": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "engine": {
                    "type": "string",
                    "enum": ["google", "duckduckgo", "youtube"],
                    "default": "google",
                },
            },
        },
    },
    {
        "type": "client",
        "name": "keyboard",
        "description": "Show, hide, or toggle the on-screen virtual keyboard. The keyboard lets the user type with their cursor by dwelling on keys.",
        "parameters": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["show", "hide", "toggle"],
                }
            },
        },
    },
    {
        "type": "client",
        "name": "narrate_screen",
        "description": "Read the current window title and any visible text aloud.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "client",
        "name": "undo",
        "description": "Undo the most recent reversible action.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "client",
        "name": "answer",
        "description": (
            "Respond conversationally without taking a computer action. "
            "Use for questions, help requests, or small talk."
        ),
        "parameters": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
    },
]


# ─── Undo history ────────────────────────────────────────────────────────────

@dataclass
class UndoRecord:
    tool: str
    description: str
    reverse_fn: Optional[Callable] = None   # None = action is not undoable


# ─── Known application name → candidate executables ─────────────────────────
#
# Order matters: first executable that resolves via shutil.which() wins.
# Anything not in this table falls through to xdg-open so the user's default
# handler picks it up (useful for file managers, browsers set as default, etc).

_APP_COMMANDS: dict[str, list[str]] = {
    "chrome":        ["google-chrome", "google-chrome-stable", "chromium", "brave-browser"],
    "google chrome": ["google-chrome", "google-chrome-stable", "chromium", "brave-browser"],
    "chromium":      ["chromium"],
    "brave":         ["brave-browser", "brave"],
    "firefox":       ["firefox", "firefox-esr"],
    "browser":       ["xdg-open", "firefox", "google-chrome", "chromium"],
    "terminal":      ["alacritty", "kitty", "gnome-terminal", "konsole", "xterm"],
    "slack":         ["slack"],
    "discord":       ["discord"],
    "code":          ["code", "code-oss", "codium"],
    "vscode":        ["code", "code-oss", "codium"],
    "spotify":       ["spotify"],
    "zoom":          ["zoom"],
    "files":         ["nautilus", "nemo", "thunar", "dolphin", "pcmanfm"],
    "file manager":  ["nautilus", "nemo", "thunar", "dolphin", "pcmanfm"],
    "calculator":    ["gnome-calculator", "kcalc", "qalculate-gtk"],
    "settings":      ["gnome-control-center", "systemsettings"],
    "email":         ["thunderbird"],
    "thunderbird":   ["thunderbird"],
    "notes":         ["gnome-text-editor", "gedit", "kate"],
}


# ─── Search engine URL templates ─────────────────────────────────────────────

_SEARCH_URLS: dict[str, str] = {
    "google":     "https://www.google.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "youtube":    "https://www.youtube.com/results?search_query={q}",
}


# ─── Virtual keyboard subprocess path ────────────────────────────────────────

_KEYBOARD_SCRIPT = Path(__file__).resolve().parent.parent / "cv" / "virtual_keyboard.py"


# ─── Dispatcher ─────────────────────────────────────────────────────────────

class ActionDispatcher:
    """
    Single point of dispatch for gesture events (CV pipeline) and
    LLM tool calls (voice pipeline).

    Usage — voice pipeline:
        dispatcher.get_client_tools()
        → pass the result dict to ElevenLabs Conversation(client_tools=...)

    Usage — CV pipeline (from matus mapping.py):
        dispatcher.execute_gesture("click", button="left")
    """

    def __init__(
        self,
        virtual_input=None,
        narrate_fn: Optional[Callable] = None,
    ):
        self._vi = virtual_input         # matus VirtualMouse, or None for pyautogui
        self._narrate = narrate_fn       # async fn() → str, set by VoiceBridge
        self._history: Deque[UndoRecord] = deque(maxlen=20)
        self._keyboard_proc: Optional[subprocess.Popen] = None
        if _HAS_PYAUTOGUI:
            self._screen_w, self._screen_h = pyautogui.size()
        else:
            # Default fallback when pyautogui isn't available (e.g. Wayland).
            # move_cursor uses normalized regions so exact screen size is only
            # required when pyautogui is the backend.
            self._screen_w, self._screen_h = 1920, 1080

    # ── Interface for ElevenLabs client_tools ────────────────────────────────

    def get_client_tools(self) -> dict[str, Callable]:
        """
        Returns the dict that ElevenLabs Conversation(client_tools=...) expects.
        Each value must be a synchronous callable that returns a result string.
        """
        return {
            "move_cursor":    self._tool_move_cursor,
            "click":          self._tool_click,
            "scroll":         self._tool_scroll,
            "type_text":      self._tool_type_text,
            "launch_app":     self._tool_launch_app,
            "search_web":     self._tool_search_web,
            "keyboard":       self._tool_keyboard,
            "narrate_screen": self._tool_narrate_screen,
            "undo":           self._tool_undo,
            "answer":         self._tool_answer,
        }

    # ── Interface for the CV pipeline ────────────────────────────────────────

    def execute_gesture(self, tool: str, **kwargs) -> None:
        """
        Called directly by the matus gesture mapping layer.
        Does not return a string — fire-and-forget.
        """
        handler = self.get_client_tools().get(tool)
        if handler:
            handler(**kwargs)

    # ── Tool handlers (synchronous — ElevenLabs requires sync client_tools) ──

    def _tool_move_cursor(self, region: str) -> str:
        if self._vi is None and _HAS_PYAUTOGUI:
            prev_x, prev_y = pyautogui.position()
        else:
            prev_x, prev_y = 0, 0
        x, y = self._region_to_coords(region)
        self._move(x, y)
        self._history.append(UndoRecord(
            tool="move_cursor",
            description=f"Moved cursor to {region}",
            reverse_fn=lambda: self._move(prev_x, prev_y),
        ))
        return f"Cursor moved to {region}."

    def _tool_click(self, button: str = "left") -> str:
        self._click(button)
        self._history.append(UndoRecord(
            tool="click",
            description=f"Clicked {button}",
            reverse_fn=None,   # clicks are not reversible
        ))
        return f"{button.capitalize()} click fired."

    def _tool_scroll(self, direction: str, amount: int = 3) -> str:
        clicks = amount if direction == "up" else -amount
        self._scroll(clicks)
        reverse = -clicks
        self._history.append(UndoRecord(
            tool="scroll",
            description=f"Scrolled {direction} {amount}",
            reverse_fn=lambda: self._scroll(reverse),
        ))
        return f"Scrolled {direction}."

    def _tool_type_text(self, text: str) -> str:
        self._type(text)
        count = len(text)
        preview = text[:30] + ("..." if len(text) > 30 else "")
        self._history.append(UndoRecord(
            tool="type_text",
            description=f"Typed: {preview}",
            reverse_fn=lambda: self._type("\b" * count),
        ))
        return f"Typed {count} characters."

    def _tool_launch_app(self, name: str) -> str:
        key = name.lower().strip()
        candidates = _APP_COMMANDS.get(key, [])
        # xdg-open fallback handles anything the user has registered a default
        # handler for (including arbitrary URIs, .desktop names, etc).
        if shutil.which("xdg-open"):
            candidates = list(candidates) + [f"xdg-open:{key}"]

        last_err: Optional[str] = None
        for cmd in candidates:
            if cmd.startswith("xdg-open:"):
                target = cmd.split(":", 1)[1]
                # xdg-open only accepts URIs or existing files — if the user
                # said "firefox" it won't resolve. Only try this when nothing
                # else worked AND the target looks like a URL.
                if not (target.startswith("http") or target.startswith("file:")):
                    continue
                exe = "xdg-open"
                args = [exe, target]
            else:
                exe = cmd
                args = [exe]
            if not shutil.which(exe):
                last_err = f"{exe} not on PATH"
                continue
            try:
                subprocess.Popen(
                    args,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._history.append(UndoRecord(
                    tool="launch_app",
                    description=f"Launched {name}",
                    reverse_fn=None,
                ))
                return f"Opening {name}."
            except Exception as exc:
                last_err = str(exc)
                continue
        detail = f" ({last_err})" if last_err else ""
        return f"{name} doesn't appear to be installed{detail}."

    def _tool_search_web(self, query: str, engine: str = "google") -> str:
        template = _SEARCH_URLS.get(engine.lower(), _SEARCH_URLS["google"])
        url = template.format(q=urllib.parse.quote_plus(query))
        # Prefer xdg-open so the user's chosen browser handles it.
        opener: list[str] = []
        if shutil.which("xdg-open"):
            opener = ["xdg-open", url]
        else:
            for br in ("firefox", "google-chrome", "chromium"):
                if shutil.which(br):
                    opener = [br, url]
                    break
        if not opener:
            return "No browser available to search with."
        try:
            subprocess.Popen(
                opener,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            return f"Search failed: {exc}"
        self._history.append(UndoRecord(
            tool="search_web",
            description=f"Searched {engine} for '{query}'",
            reverse_fn=None,
        ))
        return f"Searching {engine} for {query}."

    def _tool_keyboard(self, action: str) -> str:
        action = action.lower().strip()
        if action == "toggle":
            action = "hide" if self._keyboard_is_running() else "show"

        if action == "show":
            if self._keyboard_is_running():
                return "Keyboard already showing."
            if not _KEYBOARD_SCRIPT.exists():
                return f"Keyboard script missing at {_KEYBOARD_SCRIPT}."
            try:
                self._keyboard_proc = subprocess.Popen(
                    [sys.executable, str(_KEYBOARD_SCRIPT)],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                return f"Could not launch keyboard: {exc}"
            return "Keyboard is up. Hover a key and dwell to type."

        if action == "hide":
            if not self._keyboard_is_running():
                return "Keyboard is not showing."
            try:
                self._keyboard_proc.send_signal(signal.SIGTERM)
                self._keyboard_proc.wait(timeout=2)
            except Exception:
                try:
                    self._keyboard_proc.kill()
                except Exception:
                    pass
            self._keyboard_proc = None
            return "Keyboard hidden."

        return f"Unknown keyboard action: {action}."

    def _keyboard_is_running(self) -> bool:
        return self._keyboard_proc is not None and self._keyboard_proc.poll() is None

    def _tool_narrate_screen(self) -> str:
        if self._narrate:
            try:
                loop = asyncio.get_event_loop()
                text = loop.run_until_complete(self._narrate())
            except RuntimeError:
                text = asyncio.run(self._narrate())
            return text or "Nothing detected on screen."
        # Fallback: just the active window title via xdotool
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2,
            )
            title = result.stdout.strip()
            return f"Window: {title}" if title else "No window title available."
        except Exception:
            return "Screen narration unavailable."

    def _tool_undo(self) -> str:
        for record in reversed(list(self._history)):
            if record.reverse_fn is not None:
                record.reverse_fn()
                self._history.remove(record)
                return f"Undone: {record.description}."
        return "Nothing left to undo."

    def _tool_answer(self, text: str) -> str:
        # The LLM voices this as its spoken response; just pass it through.
        return text

    # ── Low-level input primitives ───────────────────────────────────────────

    def _move(self, x: int, y: int) -> None:
        if self._vi:
            self._vi.move(x, y)
        elif _HAS_PYAUTOGUI:
            pyautogui.moveTo(x, y, duration=0.12)

    def _click(self, button: str = "left") -> None:
        if self._vi:
            self._vi.click(button)
        elif _HAS_PYAUTOGUI:
            pyautogui.click(button=button)

    def _scroll(self, clicks: int) -> None:
        if self._vi:
            self._vi.scroll(clicks)
        elif _HAS_PYAUTOGUI:
            pyautogui.scroll(clicks)

    def _type(self, text: str) -> None:
        if self._vi:
            self._vi.type(text)
        elif _HAS_PYAUTOGUI:
            pyautogui.typewrite(text, interval=0.02)

    # ── Screen region math ───────────────────────────────────────────────────

    def _region_to_coords(self, region: str) -> tuple[int, int]:
        w, h = self._screen_w, self._screen_h
        grid = {
            "top-left":      (w // 6,      h // 6),
            "top-center":    (w // 2,      h // 6),
            "top-right":     (w * 5 // 6,  h // 6),
            "middle-left":   (w // 6,      h // 2),
            "middle":        (w // 2,      h // 2),
            "middle-right":  (w * 5 // 6,  h // 2),
            "bottom-left":   (w // 6,      h * 5 // 6),
            "bottom-center": (w // 2,      h * 5 // 6),
            "bottom-right":  (w * 5 // 6,  h * 5 // 6),
        }
        return grid.get(region, (w // 2, h // 2))