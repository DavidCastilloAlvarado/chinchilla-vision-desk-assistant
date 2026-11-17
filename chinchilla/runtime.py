"""Process level setup shared by every UI entry point."""

from __future__ import annotations

import os

from . import system


def ensure_gdk_backend() -> None:
    """Prefer XWayland so windows can position themselves and stay on top.

    Plain Wayland toplevels cannot be placed or raised by the client, and
    gtk-layer-shell is not available everywhere, so the overlay and the panel
    rely on the X11 backend when an X display exists.

    macOS GTK only ships the Quartz backend; a `DISPLAY` left by XQuartz must
    not push it to X11.
    """
    if os.environ.get("GDK_BACKEND"):
        return
    if os.environ.get("CHINCHILLA_GDK_BACKEND"):
        os.environ["GDK_BACKEND"] = os.environ["CHINCHILLA_GDK_BACKEND"]
        return
    if system.is_mac():
        return
    if os.environ.get("DISPLAY"):
        os.environ["GDK_BACKEND"] = "x11"
