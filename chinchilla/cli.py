"""Command line entry points for Chinchilla."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, paths


def _gtk_version() -> str:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except Exception as exc:  # pragma: no cover - depends on host packages
        return f"missing ({exc.__class__.__name__})"
    return f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"


def _check(label: str, detail: str, ok: bool) -> bool:
    mark = "ok  " if ok else "fail"
    print(f"[{mark}] {label}: {detail}")
    return ok


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"chinchilla {__version__}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    results = []
    results.append(_check("python", sys.version.split()[0], sys.version_info >= (3, 10)))
    gtk = _gtk_version()
    results.append(_check("gtk", gtk, not gtk.startswith("missing")))
    display = ", ".join(
        f"{key}={os.environ[key]}"
        for key in ("GDK_BACKEND", "DISPLAY", "WAYLAND_DISPLAY")
        if os.environ.get(key)
    )
    results.append(_check("session", display or "headless", bool(display)))

    try:
        paths.ensure_dirs()
        writable = os.access(paths.data_dir(), os.W_OK) and os.access(
            paths.config_dir(), os.W_OK
        )
        results.append(_check("paths", f"{paths.data_dir()} writable", writable))
    except OSError as exc:
        results.append(_check("paths", str(exc), False))

    from .core import capture

    available, _details = capture.probe_backends()
    results.append(
        _check(
            "capture",
            ", ".join(available) if available else "no capture backend available",
            bool(available),
        )
    )

    if args.verbose:
        for line in capture.describe_backends():
            print(f"       {line}")
        print(f"       config: {paths.settings_path()}")
        print(f"       data:   {paths.sessions_dir()}")
        print(f"       log:    {paths.log_path()}")

    return 0 if all(results) else 1


def _parse_rect(value: str):
    from .core.geometry import Rect

    parts = [int(part) for part in value.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("expected x,y,width,height")
    return Rect(*parts)


def cmd_overlay(args: argparse.Namespace) -> int:
    from .runtime import ensure_gdk_backend

    ensure_gdk_backend()
    from .ui import overlay

    rect = overlay.run_overlay(
        background=overlay.load_background(args.source),
        snapshot=args.snapshot,
        snapshot_delay_ms=args.snapshot_delay,
        auto_select=args.select,
        auto_complete=args.auto_complete,
        render=args.render,
    )
    if rect is None:
        print("cancelled")
        return 1
    print(f"selected {rect.width}x{rect.height} at {rect.x},{rect.y}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    import json
    import time

    from .core import capture
    from .runtime import ensure_gdk_backend

    if args.source:
        os.environ["CHINCHILLA_CAPTURE_SOURCE"] = args.source

    out = Path(args.out) if args.out else (
        paths.captures_dir() / f"capture-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    )

    try:
        if args.area:
            grab = capture.grab_area(args.backend)
            image, rect, screen_size = grab.image, None, None
        else:
            try:
                grab = capture.grab_screen(args.backend)
            except capture.CaptureError:
                grab = capture.grab_area(args.backend)
                image, rect, screen_size = grab.image, None, None
            else:
                image = grab.image
                screen_size = (image.width, image.height)
                rect = args.select
                if rect is None:
                    ensure_gdk_backend()
                    from .ui import overlay

                    rect = overlay.run_overlay(
                        background=image,
                        snapshot=args.snapshot,
                        auto_select=args.select,
                        render=args.render,
                    )
                    if rect is None:
                        print("cancelled", file=sys.stderr)
                        return 1
                image = capture.crop(image, rect, screen_size)
    except capture.CaptureError as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        return 1

    saved = capture.save_jpeg(image, out)
    payload = {
        "backend": grab.backend,
        "file": str(saved),
        "width": image.width,
        "height": image.height,
        "rect": rect.to_dict() if rect else None,
    }
    print(json.dumps(payload))
    return 0


def cmd_panel(args: argparse.Namespace) -> int:
    from .runtime import ensure_gdk_backend

    ensure_gdk_backend()
    from .ui import panel as panel_ui
    from .ui.snapshot import offscreen_pixbuf, save_pixbuf

    if args.render:
        content = panel_ui.demo_content()
        pixbuf = offscreen_pixbuf(content, panel_ui.PANEL_WIDTH, args.height)
        target = save_pixbuf(pixbuf, args.render)
        print(f"render written: {target}")
        return 0

    from .ui.gtk import Gtk, Gdk

    window = panel_ui.PanelWindow()
    window.content.set_session(
        title="New session",
        provider_label="no provider configured",
    )
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    geometry = monitor.get_geometry()
    window.show_at(geometry.width, geometry.height)
    window.content.focus_composer()
    Gtk.main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chinchilla", description=__doc__)
    parser.add_argument("--version", action="store_true", help="print the version")
    sub = parser.add_subparsers(dest="command")

    version = sub.add_parser("version", help="print the version")
    version.set_defaults(func=cmd_version)

    doctor = sub.add_parser("doctor", help="check the environment and configuration")
    doctor.add_argument("-v", "--verbose", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    capture_parser = sub.add_parser("capture", help="capture the screen or a region")
    capture_parser.add_argument("--out", help="where to write the JPEG")
    capture_parser.add_argument("--source", help="use this image instead of the live screen")
    capture_parser.add_argument("--backend", help="force a capture backend id")
    capture_parser.add_argument("--area", action="store_true", help="use the desktop area selector")
    capture_parser.add_argument("--select", type=_parse_rect, help="skip the overlay with x,y,w,h")
    capture_parser.add_argument("--snapshot", help="write a PNG of the overlay")
    capture_parser.add_argument("--render", help="render the overlay to PNG and use --select")
    capture_parser.set_defaults(func=cmd_capture)

    panel_parser = sub.add_parser("panel", help="open the response panel")
    panel_parser.add_argument("--render", help="render the panel to a PNG and exit")
    panel_parser.add_argument("--height", type=int, default=760)
    panel_parser.set_defaults(func=cmd_panel)

    overlay_parser = sub.add_parser("overlay", help="open the region selector")
    overlay_parser.add_argument("--source", help="image to use as the frozen background")
    overlay_parser.add_argument("--snapshot", help="write a PNG of the overlay itself")
    overlay_parser.add_argument("--snapshot-delay", type=int, default=900)
    overlay_parser.add_argument("--select", type=_parse_rect, help="pre-select x,y,w,h (testing)")
    overlay_parser.add_argument("--auto-complete", action="store_true")
    overlay_parser.add_argument("--render", help="render the overlay to a PNG and exit")
    overlay_parser.set_defaults(func=cmd_overlay)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False):
        return cmd_version(args)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
