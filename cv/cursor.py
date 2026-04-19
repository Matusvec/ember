"""Virtual mouse.

Linux-only: creates a new HID device via uinput that the OS treats as a real mouse.
Requires /dev/uinput writable (add user to `input` group or `sudo chmod 666 /dev/uinput`).

On non-Linux platforms, VirtualMouse() raises RuntimeError. The caller is expected to
catch that and fall back to preview-only mode.
"""

import sys

_IMPORT_ERROR: Exception | None = None
try:
    from evdev import UInput, ecodes as e
except ImportError as exc:
    _IMPORT_ERROR = exc
    UInput = None  # type: ignore[assignment]
    e = None  # type: ignore[assignment]


def _build_keymap():
    """Map each printable ASCII character to (evdev_keycode, needs_shift)."""
    if e is None:
        return {}
    km: dict[str, tuple[int, bool]] = {}
    # letters
    for c in "abcdefghijklmnopqrstuvwxyz":
        km[c] = (getattr(e, f"KEY_{c.upper()}"), False)
        km[c.upper()] = (getattr(e, f"KEY_{c.upper()}"), True)
    # digits + their shifted symbols
    digit_shift = ")!@#$%^&*("
    for i, c in enumerate("0123456789"):
        km[c] = (getattr(e, f"KEY_{c}"), False)
        km[digit_shift[i]] = (getattr(e, f"KEY_{c}"), True)
    # punctuation
    km[" "]  = (e.KEY_SPACE, False)
    km["\n"] = (e.KEY_ENTER, False)
    km["\t"] = (e.KEY_TAB, False)
    km["-"]  = (e.KEY_MINUS, False);       km["_"]  = (e.KEY_MINUS, True)
    km["="]  = (e.KEY_EQUAL, False);       km["+"]  = (e.KEY_EQUAL, True)
    km["["]  = (e.KEY_LEFTBRACE, False);   km["{"]  = (e.KEY_LEFTBRACE, True)
    km["]"]  = (e.KEY_RIGHTBRACE, False);  km["}"]  = (e.KEY_RIGHTBRACE, True)
    km["\\"] = (e.KEY_BACKSLASH, False);   km["|"]  = (e.KEY_BACKSLASH, True)
    km[";"]  = (e.KEY_SEMICOLON, False);   km[":"]  = (e.KEY_SEMICOLON, True)
    km["'"]  = (e.KEY_APOSTROPHE, False);  km['"']  = (e.KEY_APOSTROPHE, True)
    km["`"]  = (e.KEY_GRAVE, False);       km["~"]  = (e.KEY_GRAVE, True)
    km[","]  = (e.KEY_COMMA, False);       km["<"]  = (e.KEY_COMMA, True)
    km["."]  = (e.KEY_DOT, False);         km[">"]  = (e.KEY_DOT, True)
    km["/"]  = (e.KEY_SLASH, False);       km["?"]  = (e.KEY_SLASH, True)
    return km


def _build_named_keys() -> dict[str, int]:
    """Named keys the agent can press via press_key. Keys are normalized to
    lowercase; spoken variants ('return', 'space', 'esc') alias to canonical
    evdev codes."""
    if e is None:
        return {}
    nk: dict[str, int] = {
        # editing + navigation
        "enter": e.KEY_ENTER, "return": e.KEY_ENTER,
        "escape": e.KEY_ESC, "esc": e.KEY_ESC,
        "tab": e.KEY_TAB,
        "space": e.KEY_SPACE, "spacebar": e.KEY_SPACE,
        "backspace": e.KEY_BACKSPACE, "delete": e.KEY_DELETE, "del": e.KEY_DELETE,
        "insert": e.KEY_INSERT, "ins": e.KEY_INSERT,
        "home": e.KEY_HOME, "end": e.KEY_END,
        "pageup": e.KEY_PAGEUP, "page_up": e.KEY_PAGEUP, "pgup": e.KEY_PAGEUP,
        "pagedown": e.KEY_PAGEDOWN, "page_down": e.KEY_PAGEDOWN, "pgdn": e.KEY_PAGEDOWN,
        # arrows
        "up": e.KEY_UP, "down": e.KEY_DOWN,
        "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
        # media / system
        "caps": e.KEY_CAPSLOCK, "capslock": e.KEY_CAPSLOCK,
        "menu": e.KEY_MENU, "super": e.KEY_LEFTMETA, "meta": e.KEY_LEFTMETA,
        "win": e.KEY_LEFTMETA, "windows": e.KEY_LEFTMETA,
        "printscreen": e.KEY_SYSRQ, "prtsc": e.KEY_SYSRQ,
        "volumeup": e.KEY_VOLUMEUP, "volumedown": e.KEY_VOLUMEDOWN,
        "mute": e.KEY_MUTE,
        "play": e.KEY_PLAYPAUSE, "playpause": e.KEY_PLAYPAUSE,
        "next": e.KEY_NEXTSONG, "prev": e.KEY_PREVIOUSSONG, "previous": e.KEY_PREVIOUSSONG,
    }
    # F1..F24
    for i in range(1, 25):
        code = getattr(e, f"KEY_F{i}", None)
        if code is not None:
            nk[f"f{i}"] = code
    return nk


_MODIFIERS = {
    "ctrl":    "KEY_LEFTCTRL",
    "control": "KEY_LEFTCTRL",
    "alt":     "KEY_LEFTALT",
    "option":  "KEY_LEFTALT",
    "shift":   "KEY_LEFTSHIFT",
    "super":   "KEY_LEFTMETA",
    "meta":    "KEY_LEFTMETA",
    "win":     "KEY_LEFTMETA",
    "cmd":     "KEY_LEFTMETA",
    "windows": "KEY_LEFTMETA",
}


class VirtualMouse:
    """Relative-motion virtual mouse + keyboard. Call move(dx, dy) to nudge
    the cursor, type(text) to emit keystrokes for arbitrary ASCII text."""

    def __init__(self) -> None:
        if _IMPORT_ERROR is not None:
            raise RuntimeError(
                f"evdev not available ({_IMPORT_ERROR}); cursor control needs Linux + evdev"
            )
        if not sys.platform.startswith("linux"):
            raise RuntimeError("cursor control only works on Linux (uinput)")

        self.BUTTON_CODES = {"left": e.BTN_LEFT, "right": e.BTN_RIGHT, "middle": e.BTN_MIDDLE}
        self._keymap = _build_keymap()
        self._named_keys = _build_named_keys()
        # Resolve modifier keycodes once at construction time.
        self._modifier_codes = {
            name: getattr(e, code_name)
            for name, code_name in _MODIFIERS.items()
        }
        # Register every keycode the device may ever emit: ASCII typewrite,
        # named keys (Enter/arrows/F-keys/...), all modifiers.
        ascii_codes = {kc for kc, _ in self._keymap.values()}
        named_codes = set(self._named_keys.values())
        modifier_codes = set(self._modifier_codes.values())
        keyboard_keys = list(ascii_codes | named_codes | modifier_codes)
        capabilities = {
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE] + keyboard_keys,
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL],
        }
        self.ui = UInput(capabilities, name="ember-virtual-hid", version=0x1)
        self._held: set[str] = set()

    def move(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        if dx:
            self.ui.write(e.EV_REL, e.REL_X, dx)
        if dy:
            self.ui.write(e.EV_REL, e.REL_Y, dy)
        self.ui.syn()

    def press(self, button: str = "left") -> None:
        if button in self._held:
            return
        self.ui.write(e.EV_KEY, self.BUTTON_CODES[button], 1)
        self.ui.syn()
        self._held.add(button)

    def release(self, button: str = "left") -> None:
        if button not in self._held:
            return
        self.ui.write(e.EV_KEY, self.BUTTON_CODES[button], 0)
        self.ui.syn()
        self._held.discard(button)

    def click(self, button: str = "left") -> None:
        self.press(button)
        self.release(button)

    def scroll(self, clicks: int) -> None:
        if clicks == 0:
            return
        self.ui.write(e.EV_REL, e.REL_WHEEL, int(clicks))
        self.ui.syn()

    def type(self, text: str, char_delay: float = 0.015) -> None:
        """Emit keypresses for each ASCII character in `text`.

        Unknown characters (emoji, non-ASCII) are skipped silently. Voice users
        who say multilingual text should know this — for typing things like
        'hello world' or URLs, this works perfectly.
        """
        import time
        for ch in text:
            entry = self._keymap.get(ch)
            if entry is None:
                continue
            keycode, needs_shift = entry
            if needs_shift:
                self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
                self.ui.syn()
            self.ui.write(e.EV_KEY, keycode, 1)
            self.ui.syn()
            self.ui.write(e.EV_KEY, keycode, 0)
            self.ui.syn()
            if needs_shift:
                self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
                self.ui.syn()
            if char_delay > 0:
                time.sleep(char_delay)

    def key(self, keycode: int) -> None:
        """Tap a single evdev keycode once (press + release)."""
        self.ui.write(e.EV_KEY, keycode, 1)
        self.ui.syn()
        self.ui.write(e.EV_KEY, keycode, 0)
        self.ui.syn()

    def press_chord(self, chord: str) -> None:
        """Press a named key or modifier+key chord. Accepts forms like:
            'enter', 'Delete', 'Ctrl+C', 'ctrl + shift + t', 'alt+f4',
            'super+d', 'F5', 'page up'.
        Unknown tokens raise ValueError so the agent gets a clear error back.
        """
        parts = [p.strip().lower() for p in chord.replace(" ", "+").split("+") if p.strip()]
        if not parts:
            raise ValueError(f"empty key chord: {chord!r}")

        mod_codes: list[int] = []
        key_code: int | None = None
        shift_for_char = False
        for token in parts:
            if token in self._modifier_codes:
                mod_codes.append(self._modifier_codes[token])
                continue
            if key_code is not None:
                raise ValueError(f"chord has more than one non-modifier key: {chord!r}")
            # Try named key first, then single printable char (via ASCII keymap).
            if token in self._named_keys:
                key_code = self._named_keys[token]
            elif len(token) == 1:
                entry = self._keymap.get(token) or self._keymap.get(token.lower())
                if entry is None:
                    raise ValueError(f"unsupported key: {token!r} in chord {chord!r}")
                key_code, shift_for_char = entry
            else:
                raise ValueError(f"unsupported key name: {token!r} in chord {chord!r}")
        if key_code is None:
            # Chord was pure modifiers; treat last modifier as the key press.
            key_code = mod_codes.pop()

        # Shift needed by the ASCII entry (e.g. 'Ctrl+?') adds to modifier list.
        if shift_for_char and e.KEY_LEFTSHIFT not in mod_codes:
            mod_codes.append(e.KEY_LEFTSHIFT)

        # Press modifiers → tap key → release modifiers in reverse.
        for code in mod_codes:
            self.ui.write(e.EV_KEY, code, 1)
            self.ui.syn()
        self.ui.write(e.EV_KEY, key_code, 1)
        self.ui.syn()
        self.ui.write(e.EV_KEY, key_code, 0)
        self.ui.syn()
        for code in reversed(mod_codes):
            self.ui.write(e.EV_KEY, code, 0)
            self.ui.syn()

    def close(self) -> None:
        for button in list(self._held):
            self.release(button)
        self.ui.close()
