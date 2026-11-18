"""Single place that pins the GTK 3 typelib versions."""

from __future__ import annotations

import cairo  # noqa: F401  registers the cairo foreign structs
import gi

from ..runtime import ensure_gdk_backend

# GDK picks its backend the first time it opens a display, so the choice has to
# be made before anything else touches GTK: a Wayland toplevel cannot be placed
# or raised by the client, which leaves the panel lost in a corner. Doing it
# here covers every entry point, including ones that import the UI eagerly.
ensure_gdk_backend()

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import (  # noqa: E402,F401
    Gdk,
    GdkPixbuf,
    Gio,
    GLib,
    Gtk,
    Pango,
    PangoCairo,
)
