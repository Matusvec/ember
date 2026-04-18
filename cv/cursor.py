"""Virtual mouse via Linux uinput. Creates a new HID device the OS treats as a real mouse.

Requirements:
  - /dev/uinput writable by current user (add to `input` group or chmod 666)
  - python-evdev

The physical mouse/trackpad keeps working — this is an ADDITIONAL pointing device.
"""

from evdev import UInput, ecodes as e


class VirtualMouse:
    """Relative-motion virtual mouse. Call move(dx, dy) to nudge the cursor."""

    BUTTON_CODES = {"left": e.BTN_LEFT, "right": e.BTN_RIGHT, "middle": e.BTN_MIDDLE}

    def __init__(self) -> None:
        capabilities = {
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL],
        }
        self.ui = UInput(capabilities, name="axis-virtual-mouse", version=0x1)
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

    def close(self) -> None:
        for button in list(self._held):
            self.release(button)
        self.ui.close()
