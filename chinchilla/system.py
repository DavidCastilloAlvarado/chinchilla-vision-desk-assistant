"""Which desktop family the process runs on.

Functions instead of constants so tests can pretend to be the other platform.
"""

from __future__ import annotations

import sys


def is_mac() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")
