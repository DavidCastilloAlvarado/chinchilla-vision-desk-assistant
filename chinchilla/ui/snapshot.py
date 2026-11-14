"""Dev helper: write a PNG of a window's own pixels.

Works on the X11 backend only; that is the backend the UI runs on by default,
so it is a reliable way to verify rendering without a screen recorder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cairo

from .gtk import Gdk, GdkPixbuf, GLib, Gtk  # noqa: F401


def window_pixbuf(window: Gtk.Window) -> Gdk.Pixbuf | None:
    gdk_window = window.get_window()
    if gdk_window is None:
        return None
    allocation = window.get_allocation()
    if allocation.width <= 1 or allocation.height <= 1:
        return None
    return Gdk.pixbuf_get_from_window(
        gdk_window, 0, 0, allocation.width, allocation.height
    )


def save_window_snapshot(window: Gtk.Window, path: str | Path) -> bool:
    pixbuf = window_pixbuf(window)
    if pixbuf is None:
        return False
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(path), "png", [], [])
    return True


def snapshot_after(window: Gtk.Window, path: str | Path, delay_ms: int = 800) -> None:
    def shoot() -> bool:
        ok = save_window_snapshot(window, path)
        print(f"snapshot {'written' if ok else 'failed'}: {path}", flush=True)
        return False

    GLib.timeout_add(delay_ms, shoot)


def render_cairo(
    render: Callable[[cairo.Context, int, int], None],
    path: str | Path,
    width: int,
    height: int,
    scale: float = 1.0,
) -> Path:
    """Render a custom draw routine straight into a PNG (no window needed)."""
    surface = cairo.ImageSurface(
        cairo.FORMAT_ARGB32, int(width * scale), int(height * scale)
    )
    cr = cairo.Context(surface)
    cr.scale(scale, scale)
    render(cr, width, height)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    surface.write_to_png(str(target))
    return target


def offscreen_pixbuf(
    widget: Gtk.Widget,
    width: int,
    height: int,
    prepare: Callable[[], None] | None = None,
) -> GdkPixbuf.Pixbuf:
    """Paint a widget tree without showing a window.

    `prepare` runs once the tree is realized, which is the only moment some
    widgets (a notebook's current page, for instance) accept a change.
    """
    holder = Gtk.OffscreenWindow()
    holder.set_default_size(width, height)
    holder.add(widget)
    holder.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    if prepare is not None:
        prepare()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
    pixbuf = holder.get_pixbuf()
    holder.remove(widget)
    holder.destroy()
    if pixbuf is None:
        raise RuntimeError("widget did not render")
    return pixbuf


def save_pixbuf(pixbuf: GdkPixbuf.Pixbuf, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pixbuf.savev(str(target), "png", [], [])
    return target
