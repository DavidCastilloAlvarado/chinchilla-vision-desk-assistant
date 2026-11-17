"""Images the user puts on the clipboard with macOS's own screenshot tool.

Without the Screen Recording grant nothing this process runs can read the
screen, `screencapture -i` included. The system screenshot UI is not bound by
it: ⌘⌃⇧4 copies the region the user drags to the pasteboard, which any app may
read. On a managed Mac where only an admin can grant Screen Recording, that is
how a cut reaches Chinchilla.
"""

from __future__ import annotations

import ctypes
import io
import time
from typing import Callable

from PIL import Image

from . import cocoa

TYPES = (b"public.png", b"public.tiff")
POLL_SECONDS = 0.3


class _Pool:
    """Autorelease pool, so polls outside the AppKit loop do not leak."""

    def __enter__(self):
        lib = cocoa._objc()
        lib.objc_autoreleasePoolPush.restype = ctypes.c_void_p
        lib.objc_autoreleasePoolPop.argtypes = [ctypes.c_void_p]
        self._token = lib.objc_autoreleasePoolPush()
        return self

    def __exit__(self, *_exc) -> None:
        cocoa._objc().objc_autoreleasePoolPop(self._token)


def _general():
    return cocoa._send(cocoa._objc().objc_getClass(b"NSPasteboard"), "generalPasteboard")


def change_count() -> int:
    """Bumps every time anything is copied; cheap enough to poll."""
    with _Pool():
        return int(cocoa._send(_general(), "changeCount", restype=ctypes.c_long))


def read_image() -> Image.Image | None:
    with _Pool():
        board = _general()
        string_class = cocoa._objc().objc_getClass(b"NSString")
        for uti in TYPES:
            name = cocoa._send(
                string_class, "stringWithUTF8String:", uti, argtypes=[ctypes.c_char_p]
            )
            data = cocoa._send(board, "dataForType:", name, argtypes=[ctypes.c_void_p])
            if not data:
                continue
            length = cocoa._send(data, "length", restype=ctypes.c_ulong)
            if not length:
                continue
            raw = ctypes.string_at(cocoa._send(data, "bytes"), length)
            try:
                return Image.open(io.BytesIO(raw)).convert("RGB")
            except (OSError, Image.DecompressionBombError):
                continue
    return None


def wait_for_image(
    timeout: float,
    since: int | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Image.Image | None:
    """Block until an image is copied; copied text is skipped. None on timeout."""
    start = change_count() if since is None else since
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled is not None and cancelled():
            return None
        count = change_count()
        if count != start:
            start = count
            image = read_image()
            if image is not None:
                return image
        time.sleep(POLL_SECONDS)
    return None
