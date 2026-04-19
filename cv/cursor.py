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
        # Include every keycode we'll ever emit plus shift.
        keyboard_keys = list({kc for kc, _ in self._keymap.values()}) + [
            e.KEY_LEFTSHIFT, e.KEY_BACKSPACE, e.KEY_ENTER, e.KEY_TAB,
        ]
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

    def close(self) -> None:
        for button in list(self._held):
            self.release(button)
        self.ui.close()
