"""Mapping config + dispatcher.

mapping.json holds user bindings and tuning. MappingConfig loads it and watches
the file's mtime — any edit is picked up without restarting the preview.

MappingDispatcher takes a per-frame dict of source values and applies enabled
bindings to the VirtualMouse.  New source/action types are added here.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cursor import VirtualMouse


@dataclass
class Binding:
    id: str
    source: str
    action: str
    enabled: bool
    params: dict[str, Any]


class MappingConfig:
    """Loads mapping.json and hot-reloads on file change."""

    def __init__(self, path: str | Path = "mapping.json") -> None:
        self.path = Path(path)
        self._mtime: float = 0.0
        self.cursor_sensitivity: float = 2500
        self.filter_min_cutoff: float = 1.0
        self.filter_beta: float = 0.05
        self.bindings: list[Binding] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            print(f"WARN: {self.path} not found — dispatcher will be a no-op", flush=True)
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            print(f"WARN: {self.path} parse error ({exc}) — keeping old config", flush=True)
            return

        self.cursor_sensitivity = float(raw.get("cursor_sensitivity", 2500))
        filt = raw.get("filter", {})
        self.filter_min_cutoff = float(filt.get("min_cutoff", 1.0))
        self.filter_beta = float(filt.get("beta", 0.05))

        new_bindings: list[Binding] = []
        for b in raw.get("bindings", []):
            known_keys = {"id", "source", "action", "enabled"}
            params = {k: v for k, v in b.items() if k not in known_keys}
            new_bindings.append(
                Binding(
                    id=b["id"],
                    source=b["source"],
                    action=b["action"],
                    enabled=bool(b.get("enabled", True)),
                    params=params,
                )
            )
        self.bindings = new_bindings
        self._mtime = self.path.stat().st_mtime
        print(
            f"mapping: loaded {len(self.bindings)} bindings, "
            f"{sum(1 for b in self.bindings if b.enabled)} enabled, "
            f"sensitivity={self.cursor_sensitivity}",
            flush=True,
        )

    def maybe_reload(self) -> bool:
        """Poll file mtime.  Returns True if config was reloaded this call."""
        if not self.path.exists():
            return False
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if mtime > self._mtime:
            self.load()
            return True
        return False


class MappingDispatcher:
    """Turns per-frame source values into driver actions, per the config."""

    def __init__(self, config: MappingConfig, mouse: VirtualMouse | None) -> None:
        self.config = config
        self.mouse = mouse
        self._cursor_state: dict[str, Any] = {}      # filter state per binding
        self._button_held: dict[str, bool] = {}       # per binding
        self._blink_state: dict[str, Any] = {}        # per binding
        from filters import OneEuroFilter
        self._make_filter = OneEuroFilter

    def dispatch(self, sources: dict[str, Any], now: float) -> list[str]:
        """Apply all enabled bindings.  Returns list of event labels fired (for UI)."""
        events: list[str] = []
        if self.mouse is None:
            return events

        for b in self.config.bindings:
            if not b.enabled:
                self._maybe_release(b)
                continue

            if b.action == "cursor_xy":
                pos = sources.get(b.source)
                if pos is None:
                    continue
                self._handle_cursor(b, pos, now)
                events.append(f"{b.source}→cursor")

            elif b.action == "left_press":
                value = sources.get(b.source)
                if value is None:
                    continue
                threshold = b.params.get("threshold", 0.08)
                pressed = value > threshold
                self._handle_button_hold(b, pressed, "left")
                if pressed:
                    events.append(f"{b.source}→HOLD")

            elif b.action in ("left_click", "right_click", "middle_click"):
                button = b.action.split("_")[0]
                if b.source == "blink":
                    self._handle_blink_click(b, sources.get("ear"), now, button)
                    if self._blink_state.get(b.id, {}).get("closed", False):
                        events.append(f"{b.source}→CLOSED")
                else:
                    value = sources.get(b.source)
                    if value is None:
                        continue
                    threshold = b.params.get("threshold", 0.5)
                    self._handle_edge_click(b, value > threshold, button)

            elif b.action == "keypress":
                # Stub — to wire up once we add virtual keyboard support.
                continue

        return events

    # ---- helpers ----

    def _handle_cursor(self, b: Binding, pos: tuple[float, float], now: float) -> None:
        st = self._cursor_state.setdefault(b.id, {
            "fx": self._make_filter(
                min_cutoff=self.config.filter_min_cutoff,
                beta=self.config.filter_beta,
            ),
            "fy": self._make_filter(
                min_cutoff=self.config.filter_min_cutoff,
                beta=self.config.filter_beta,
            ),
            "prev": None,
            "rem_x": 0.0,
            "rem_y": 0.0,
            "last_seen": 0.0,
        })
        if now - st["last_seen"] > 0.3:
            st["fx"].reset()
            st["fy"].reset()
            st["prev"] = None
            st["rem_x"] = st["rem_y"] = 0.0

        sx = st["fx"].filter(pos[0], now)
        sy = st["fy"].filter(pos[1], now)
        smooth = (sx, sy)

        if st["prev"] is not None:
            sens = self.config.cursor_sensitivity
            inv_x = -1 if b.params.get("invert_x") else 1
            inv_y = -1 if b.params.get("invert_y") else 1
            move_x = (smooth[0] - st["prev"][0]) * sens * inv_x + st["rem_x"]
            move_y = (smooth[1] - st["prev"][1]) * sens * inv_y + st["rem_y"]
            int_x = int(move_x)
            int_y = int(move_y)
            st["rem_x"] = move_x - int_x
            st["rem_y"] = move_y - int_y
            if abs(int_x) >= 1 or abs(int_y) >= 1:
                self.mouse.move(int_x, int_y)

        st["prev"] = smooth
        st["last_seen"] = now

    def _handle_button_hold(self, b: Binding, pressed: bool, button: str) -> None:
        was = self._button_held.get(b.id, False)
        if pressed and not was:
            self.mouse.press(button)
        elif not pressed and was:
            self.mouse.release(button)
        self._button_held[b.id] = pressed

    def _handle_edge_click(self, b: Binding, active: bool, button: str) -> None:
        was = self._button_held.get(b.id, False)
        if active and not was:
            self.mouse.click(button)
        self._button_held[b.id] = active

    def _handle_blink_click(self, b: Binding, ear: float | None, now: float, button: str) -> None:
        if ear is None:
            return
        st = self._blink_state.setdefault(b.id, {"closed": False, "closed_since": 0.0, "fired": False})
        threshold = b.params.get("ear_threshold", 0.18)
        min_ms = b.params.get("min_closed_ms", 200)
        is_closed = ear < threshold

        if is_closed and not st["closed"]:
            st["closed_since"] = now
            st["fired"] = False
        elif is_closed and st["closed"]:
            if not st["fired"] and (now - st["closed_since"]) * 1000 >= min_ms:
                self.mouse.click(button)
                st["fired"] = True
        st["closed"] = is_closed

    def _maybe_release(self, b: Binding) -> None:
        """If a binding was just disabled while holding a button, release it cleanly."""
        if self._button_held.get(b.id, False):
            if b.action == "left_press":
                self.mouse.release("left")
            self._button_held[b.id] = False
