"""Frozen-frame region selector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import cairo
from PIL import Image

from .gtk import Gdk, GdkPixbuf, GLib, Gtk

from ..core.geometry import Rect, clamp, from_points, is_usable, nudge
from .. import system
from . import paint, theme

VEIL = (0.02, 0.03, 0.05, 0.44)
HINT = "Drag to select  |  arrows nudge  |  Enter confirm  |  Esc cancel"


def screen_size() -> tuple[int, int]:
    """Size of the area the overlay covers, in the coordinates it reports.

    The selection is in logical points while the frozen frame is in pixels
    (twice as many on a Retina or 200% display), so crops scale between both.
    """
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    geometry = monitor.get_geometry()
    return geometry.width, geometry.height


class SelectionOverlay(Gtk.Window):
    """Transparent fullscreen window that reports the dragged rectangle."""

    def __init__(
        self,
        background: Image.Image | None = None,
        on_complete: Callable[[Rect], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        hint: str = HINT,
    ) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True)
        self.set_can_focus(True)

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geometry = monitor.get_geometry()
        self._screen = Rect(geometry.x, geometry.y, geometry.width, geometry.height)
        self.set_default_size(self._screen.width, self._screen.height)

        self._background = background
        self._surface = None
        self._surface_data = None
        self._bg_size = (0, 0)
        # GTK has no cairo paint context without python3-gi-cairo, so the frame
        # is drawn into a cairo surface and handed to the window as a pixbuf.
        # Cairo stores pixels as BGRA and the pixbuf reads RGBA, so the live
        # frame is drawn with the red and blue channels swapped: that keeps the
        # colours right without copying eight megabytes on every mouse move.
        self._bgr = True
        if background is not None:
            self._surface, self._surface_data = paint.surface_from_image(
                self._swapped(background) if self._bgr else background
            )
            self._bg_size = (background.width, background.height)

        self._image = Gtk.Image()
        self._image.set_halign(Gtk.Align.FILL)
        self._image.set_valign(Gtk.Align.FILL)
        self.add(self._image)
        self._pending = False
        self._frame = None
        self._frame_bytes = b""
        self._frame_gbytes = None
        self._frame_pixbuf = None

        self._on_complete = on_complete
        self._on_cancel = on_cancel
        self._hint = hint
        self._origin: tuple[int, int] | None = None
        self._rect: Rect | None = None
        self._cursor: tuple[int, int] = (self._screen.width // 2, self._screen.height // 2)
        self._grab = None
        self._finished = False

        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.STRUCTURE_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
        )
        self.connect("button-press-event", self._on_button_press)
        self.connect("button-release-event", self._on_button_release)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("key-press-event", self._on_key)

    # ------------------------------------------------------------------ colour

    @staticmethod
    def _swapped(image: Image.Image) -> Image.Image:
        red, green, blue = image.convert("RGB").split()
        return Image.merge("RGB", (blue, green, red))

    def _color(self, red: float, green: float, blue: float, alpha: float | None = None):
        if self._bgr:
            red, blue = blue, red
        if alpha is None:
            return (red, green, blue)
        return (red, green, blue, alpha)

    # ------------------------------------------------------------------ window

    def start(self) -> None:
        self.move(self._screen.x, self._screen.y)
        self._repaint()
        self.show_all()
        if system.is_mac():
            # fullscreen() on Quartz slides into a new Space; a borderless
            # window the size of the display lifted above the menu bar and the
            # Dock behaves like the system selector instead
            from ..macos import cocoa

            self.resize(self._screen.width, self._screen.height)
            cocoa.activate()
            self.present()
            cocoa.raise_window(self, cocoa.LEVEL_SCREEN_SAVER, all_spaces=True)
        else:
            self.fullscreen()
            self.present()
        self._set_cursor()
        self._grab_seat()

    def _set_cursor(self) -> None:
        display = Gdk.Display.get_default()
        gdk_window = self.get_window()
        if gdk_window is not None:
            gdk_window.set_cursor(Gdk.Cursor.new_from_name(display, "crosshair"))

    def _grab_seat(self) -> None:
        display = Gdk.Display.get_default()
        seat = display.get_default_seat()
        if seat is None or self.get_window() is None:
            return
        try:
            self._grab = seat.grab(
                self.get_window(),
                Gdk.SeatCapabilities.ALL,
                False,
                Gdk.Cursor.new_from_name(display, "crosshair"),
                None,
                None,
            )
        except Exception:  # pragma: no cover - depends on the compositor
            self._grab = None

    def _release_seat(self) -> None:
        if self._grab is not None:
            try:
                self._grab.release()
            except Exception:  # pragma: no cover
                pass
            self._grab = None

    def finish(self, rect: Rect | None) -> None:
        if self._finished:
            return
        self._finished = True
        self._release_seat()
        self.destroy()
        if rect is not None and self._on_complete:
            self._on_complete(rect)
        elif rect is None and self._on_cancel:
            self._on_cancel()

    # ------------------------------------------------------------------ events

    def _bounds(self) -> tuple[int, int]:
        return (self._screen.width, self._screen.height)

    def _on_button_press(self, _widget, event) -> bool:
        if event.button != 1:
            return False
        self._origin = (int(event.x), int(event.y))
        self._rect = Rect(int(event.x), int(event.y), 0, 0)
        self._invalidate()
        return True

    def _on_motion(self, _widget, event) -> bool:
        self._cursor = (int(event.x), int(event.y))
        if self._origin is not None:
            self._rect = from_points(*self._origin, int(event.x), int(event.y), self._bounds())
        self._invalidate()
        return True

    def _on_button_release(self, _widget, event) -> bool:
        if event.button != 1 or self._origin is None:
            return False
        rect = from_points(*self._origin, int(event.x), int(event.y), self._bounds())
        self._origin = None
        if is_usable(rect):
            self.finish(rect)
        else:
            self._rect = None
            self._invalidate()
        return True

    def _on_key(self, _widget, event) -> bool:
        key = event.keyval
        if key == Gdk.KEY_Escape:
            self.finish(None)
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self._rect is not None and is_usable(self._rect):
                self.finish(self._rect)
            return True
        if key == Gdk.KEY_BackSpace:
            self._rect = None
            self._origin = None
            self._invalidate()
            return True
        step = 10 if event.state & Gdk.ModifierType.SHIFT_MASK else 1
        deltas = {
            Gdk.KEY_Left: (-step, 0),
            Gdk.KEY_Right: (step, 0),
            Gdk.KEY_Up: (0, -step),
            Gdk.KEY_Down: (0, step),
        }
        if key in deltas:
            if self._rect is None:
                self._rect = Rect(0, 0, 0, 0)
            width, height = self._bounds()
            self._rect = nudge(self._rect, *deltas[key], width, height)
            self._invalidate()
            return True
        return False

    # ----------------------------------------------------------------- drawing

    def _invalidate(self) -> None:
        """Coalesces repaints: motion events are much faster than full redraws."""
        if self._pending:
            return
        self._pending = True
        GLib.idle_add(self._repaint)

    def _repaint(self) -> bool:
        self._pending = False
        width, height = self._screen.width, self._screen.height
        if self._frame is None:
            self._frame = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
        cr = cairo.Context(self._frame)
        self.render(cr, width, height)
        self._frame.flush()
        # the pixbuf borrows the buffer instead of copying it, so both the
        # bytes and the GBytes have to outlive the call
        self._frame_bytes = bytes(self._frame.get_data())
        self._frame_gbytes = GLib.Bytes.new(self._frame_bytes)
        self._frame_pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            self._frame_gbytes,
            GdkPixbuf.Colorspace.RGB,
            True,  # four channels keeps the data byte aligned with the surface
            8,
            width,
            height,
            self._frame.get_stride(),
        )
        self._image.set_from_pixbuf(self._frame_pixbuf)
        return False

    def render(self, cr, width: int, height: int) -> None:
        """Draw the whole overlay; shared by the live window and snapshots."""
        cr.set_operator(cairo.OPERATOR_OVER)
        self._paint_background(cr, width, height)

        rect = self._rect
        if rect is None or not is_usable(rect):
            cr.set_source_rgba(*self._color(*VEIL))
            cr.paint()
        else:
            self._paint_veil_around(cr, rect, width, height)
            self._paint_selection(cr, rect, width, height)
        self._paint_hint(cr, width, height)
        if rect is not None and is_usable(rect):
            self._paint_magnifier(cr, width, height)

    def render_to_png(self, path: str | Path) -> Path:
        from .snapshot import render_cairo

        previous, self._bgr = self._bgr, False
        try:
            return render_cairo(
                self.render, path, self._screen.width, self._screen.height
            )
        finally:
            self._bgr = previous

    def _paint_background(self, cr, width: int | None = None, height: int | None = None) -> None:
        width = width or self._screen.width
        height = height or self._screen.height
        if self._surface is None:
            cr.set_source_rgb(*self._color(0.06, 0.07, 0.09)[:3])
            cr.paint()
            return
        cr.save()
        cr.scale(width / self._bg_size[0], height / self._bg_size[1])
        cr.set_source_surface(self._surface, 0, 0)
        cr.paint()
        cr.restore()

    def _paint_veil_around(self, cr, rect: Rect, width: int, height: int) -> None:
        cr.set_source_rgba(*self._color(*VEIL))
        for x, y, w, h in (
            (0, 0, width, rect.y),
            (0, rect.bottom, width, height - rect.bottom),
            (0, rect.y, rect.x, rect.height),
            (rect.right, rect.y, width - rect.right, rect.height),
        ):
            if w > 0 and h > 0:
                cr.rectangle(x, y, w, h)
        cr.fill()

    def _paint_selection(self, cr, rect: Rect, width: int, height: int) -> None:
        cr.set_source_rgba(*self._color(*theme.ACCENT))
        cr.set_line_width(2)
        cr.rectangle(rect.x + 0.5, rect.y + 0.5, rect.width, rect.height)
        cr.stroke()

        cr.set_source_rgba(*self._color(1, 1, 1, 0.22))
        cr.set_line_width(1)
        cr.rectangle(rect.x + 1.5, rect.y + 1.5, rect.width - 1, rect.height - 1)
        cr.stroke()

        self._paint_handles(cr, rect)

        cr.set_source_rgba(*self._color(1, 1, 1, 0.18))
        cr.set_line_width(1)
        cr.set_dash([4, 4], 0)
        cr.move_to(self._cursor[0], 0)
        cr.line_to(self._cursor[0], height)
        cr.move_to(0, self._cursor[1])
        cr.line_to(width, self._cursor[1])
        cr.stroke()
        cr.set_dash([], 0)

        self._paint_badge(cr, rect, width)

    def _paint_handles(self, cr, rect: Rect) -> None:
        """Round grips on the corners and edge midpoints, like the GNOME picker."""
        radius = 4.0
        points = [
            (rect.x, rect.y),
            (rect.x + rect.width / 2, rect.y),
            (rect.right, rect.y),
            (rect.right, rect.y + rect.height / 2),
            (rect.right, rect.bottom),
            (rect.x + rect.width / 2, rect.bottom),
            (rect.x, rect.bottom),
            (rect.x, rect.y + rect.height / 2),
        ]
        for cx, cy in points:
            cr.set_source_rgba(*self._color(0.98, 0.98, 0.96, 0.95))
            cr.arc(cx, cy, radius, 0, 2 * 3.141592653589793)
            cr.fill()
            cr.set_source_rgba(*self._color(*theme.ACCENT))
            cr.set_line_width(1.5)
            cr.arc(cx, cy, radius, 0, 2 * 3.141592653589793)
            cr.stroke()

    def _paint_badge(self, cr, rect: Rect, width: int) -> None:
        text = f"{rect.width} x {rect.height}"
        tw, th = paint.text_size(text, 12, bold=True)
        pad = 7
        bw, bh = tw + pad * 2, th + pad
        bx = min(max(0, rect.x), width - bw)
        by = rect.y - bh - 6
        if by < 0:
            by = rect.y + 6
        cr.set_source_rgba(*self._color(*theme.ACCENT))
        cr.rectangle(bx, by, bw, bh)
        cr.fill()
        paint.draw_text(
            cr, text, bx + pad / 2, by + (bh - th) / 2, 12, self._color(0.09, 0.08, 0.05)[:3], True
        )

    def _paint_hint(self, cr, width: int, height: int) -> None:
        if not self._hint:
            return
        tw, th = paint.text_size(self._hint, 11)
        pad = 12
        bx = (width - tw) / 2 - pad
        by = 24.0
        cr.set_source_rgba(*self._color(0.06, 0.07, 0.09, 0.82))
        cr.rectangle(bx, by, tw + pad * 2, th + pad)
        cr.fill()
        paint.draw_text(
            cr, self._hint, bx + pad / 2, by + (th + pad - th) / 2, 11, self._color(0.92, 0.90, 0.86)[:3]
        )
        del height

    def _paint_magnifier(self, cr, width: int, height: int) -> None:
        if self._surface is None:
            return
        size, zoom = 132, 3
        cx, cy = self._cursor
        bx = width - size - 24 if cx < width / 2 else 24
        by = height - size - 24 if cy < height / 2 else 24
        sx = self._screen.width / self._bg_size[0]
        sy = self._screen.height / self._bg_size[1]

        cr.save()
        cr.rectangle(bx, by, size, size)
        cr.clip()
        cr.translate(bx + size / 2, by + size / 2)
        cr.scale(zoom * sx, zoom * sy)
        cr.translate(-cx / sx, -cy / sy)
        cr.set_source_surface(self._surface, 0, 0)
        cr.paint()
        cr.restore()

        cr.set_source_rgba(*self._color(*theme.ACCENT))
        cr.set_line_width(1.5)
        cr.rectangle(bx + 0.5, by + 0.5, size, size)
        cr.stroke()
        cr.set_source_rgba(*self._color(1, 1, 1, 0.7))
        cr.move_to(bx + size / 2 - 8, by + size / 2)
        cr.line_to(bx + size / 2 + 8, by + size / 2)
        cr.move_to(bx + size / 2, by + size / 2 - 8)
        cr.line_to(bx + size / 2, by + size / 2 + 8)
        cr.stroke()

    # ------------------------------------------------------------------- utils

    def select_for_test(self, rect: Rect) -> None:
        """Select a rect programmatically, used by the snapshot harness."""
        self._rect = clamp(rect, *self._bounds())
        self._cursor = (self._rect.right, self._rect.bottom)
        self._invalidate()

    def complete_for_test(self) -> None:
        if self._rect is not None and is_usable(self._rect):
            self.finish(self._rect)


def run_overlay(
    background: Image.Image | None = None,
    snapshot: str | None = None,
    snapshot_delay_ms: int = 900,
    auto_select: Rect | None = None,
    auto_complete: bool = False,
    render: str | None = None,
) -> Rect | None:
    """Run the overlay in its own GTK loop. Returns the selected rect."""
    result: dict[str, Rect | None] = {"rect": None}
    holder: dict[str, SelectionOverlay] = {}

    def done(rect: Rect) -> None:
        result["rect"] = rect
        Gtk.main_quit()

    def cancelled() -> None:
        result["rect"] = None
        Gtk.main_quit()

    overlay = SelectionOverlay(background=background, on_complete=done, on_cancel=cancelled)
    holder["overlay"] = overlay

    if render:
        if auto_select is not None:
            overlay.select_for_test(auto_select)
        path = overlay.render_to_png(render)
        print(f"render written: {path}")
        rect = overlay._rect
        overlay.destroy()
        print(json.dumps({"rect": rect.to_dict() if rect else None, "render": str(path)}))
        return rect

    overlay.start()

    if auto_select is not None:
        GLib.timeout_add(250, lambda: (overlay.select_for_test(auto_select), False)[1])
        if auto_complete:
            delay = max(450, snapshot_delay_ms + 300) if snapshot else 450
            GLib.timeout_add(delay, lambda: (overlay.complete_for_test(), False)[1])
    if snapshot:
        from .snapshot import snapshot_after

        snapshot_after(overlay, snapshot, snapshot_delay_ms)
        GLib.timeout_add(snapshot_delay_ms + 400, lambda: (Gtk.main_quit(), False)[1])

    Gtk.main()
    if overlay.get_window() is not None:
        overlay.destroy()
    rect = result["rect"]
    print(json.dumps({"rect": rect.to_dict() if rect else None, "snapshot": snapshot}))
    return rect


def load_background(path: str | Path | None) -> Image.Image | None:
    if not path:
        return None
    return Image.open(path)
