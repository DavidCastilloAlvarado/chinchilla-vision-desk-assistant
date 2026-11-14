"""Single place that pins the GTK 3 typelib versions."""

from __future__ import annotations

import cairo  # noqa: F401  registers the cairo foreign structs
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import (  # noqa: E402,F401
    Gdk,
    GdkPixbuf,
    GLib,
    Gtk,
    Pango,
    PangoCairo,
)
