"""Screen Recording access (the macOS privacy grant behind `screencapture`).

Without it macOS still answers a capture, but with only the wallpaper and the
menu bar: every other window is blanked. The grant belongs to the app that is
"responsible" for this process (Terminal, iTerm, VS Code, or Python itself when
the login agent starts it), and macOS only re-reads it when that app restarts.
"""

from __future__ import annotations

import ctypes
import subprocess
from functools import lru_cache

from .. import log

LOGGER = log.get("macos")
SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
PANE = "System Settings \u203a Privacy & Security \u203a Screen & System Audio Recording"


@lru_cache(maxsize=1)
def _core_graphics():
    lib = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    lib.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
    lib.CGPreflightScreenCaptureAccess.argtypes = []
    lib.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
    lib.CGRequestScreenCaptureAccess.argtypes = []
    return lib


def is_granted() -> bool:
    try:
        return bool(_core_graphics().CGPreflightScreenCaptureAccess())
    except (OSError, AttributeError) as exc:
        LOGGER.warning("cannot read the Screen Recording grant: %s", exc)
        return False


def request() -> bool:
    """Ask once; macOS shows its prompt only the first time and then stays quiet."""
    try:
        return bool(_core_graphics().CGRequestScreenCaptureAccess())
    except (OSError, AttributeError) as exc:
        LOGGER.warning("cannot request the Screen Recording grant: %s", exc)
        return False


def open_settings() -> bool:
    try:
        subprocess.run(["open", SETTINGS_URL], check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.warning("cannot open System Settings: %s", exc)
        return False
    return True
