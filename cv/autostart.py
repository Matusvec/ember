"""XDG autostart installer — run Ember on login.

Writes ~/.config/autostart/ember.desktop so the user's desktop environment
(GNOME, KDE, XFCE, hyprland with xdg-autostart, etc.) launches Ember on
every login. One-shot; user can uninstall via --uninstall-autostart.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "ember.desktop"


def _desktop_file_contents(axis_path: Path, python_path: Path) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=Ember
Comment=Adaptive accessibility input layer
Exec={python_path} {axis_path} --no-onboard
Terminal=false
X-GNOME-Autostart-enabled=true
Hidden=false
NoDisplay=false
"""


def install(axis_path: Path | str | None = None, python_path: Path | str | None = None) -> Path:
    """Write the autostart .desktop file. Returns the path written."""
    axis_path = Path(axis_path or (Path(__file__).resolve().parent.parent / "axis.py"))
    python_path = Path(python_path or sys.executable)

    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    AUTOSTART_FILE.write_text(_desktop_file_contents(axis_path, python_path))
    # Mark executable — some DEs care.
    AUTOSTART_FILE.chmod(0o755)
    return AUTOSTART_FILE


def uninstall() -> bool:
    """Remove the autostart entry. Returns True if a file was removed."""
    if AUTOSTART_FILE.exists():
        AUTOSTART_FILE.unlink()
        return True
    return False


def is_installed() -> bool:
    return AUTOSTART_FILE.exists()


def can_install() -> bool:
    """Rudimentary sanity check — XDG autostart assumes a desktop env."""
    # ~/.config always exists on a logged-in user's account; that's enough.
    return Path.home().exists() and shutil.which("sh") is not None
