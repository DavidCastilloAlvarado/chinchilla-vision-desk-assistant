"""Command line entry points for Chinchilla."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import __version__, paths
from .shortcuts import DEFAULT_BINDING


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
    from .store import config

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

    settings = config.load_settings()
    provider = config.resolved_provider(settings)
    source = config.key_source(provider.id)
    results.append(
        _check(
            "provider",
            f"{provider.id} model={provider.model or 'unset'} key={source}",
            bool(provider.model) and source != "missing",
        )
    )

    from .core import capture

    available, _details = capture.probe_backends()
    results.append(
        _check(
            "capture",
            ", ".join(available) if available else "no capture backend available",
            bool(available),
        )
    )

    from .core import search

    web_ok, web_detail = search.probe_server(settings)
    results.append(_check("websearch", web_detail, web_ok))

    from . import shortcuts

    shortcut = shortcuts.status()
    results.append(
        _check("shortcut", shortcut.summary, shortcut.installed)
    )

    if args.verbose:
        for line in capture.describe_backends():
            print(f"       {line}")
        _command, web_env = config.resolved_mcp(settings)
        print(f"       websearch env: npx in {Path(_command[0]).parent}")
        print(f"       chrome: {web_env.get('CHROME_PATH')}")
        print(f"       profile: {web_env.get('GSEARCH_PROFILE')}")
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

    # the backend has to be chosen before anything imports the UI, otherwise
    # GTK opens the Wayland display and the panel has no X11 handle to give
    # the screenshot portal
    ensure_gdk_backend()
    if args.panel:
        from .ui.app import run_app

        return run_app([])

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


def cmd_ask(args: argparse.Namespace) -> int:
    from .core import llm
    from .core.prompts import SYSTEM_PROMPT
    from .store import config

    settings = config.load_settings()
    images = []
    if args.image:
        from PIL import Image

        from .core import capture

        images.append(capture.encode_jpeg(Image.open(args.image), max_side=settings.max_side))

    try:
        provider = llm.build_provider(settings)
    except llm.ProviderError as exc:
        print(f"no provider: {exc}", file=sys.stderr)
        return 1

    messages = [
        llm.Message("system", SYSTEM_PROMPT),
        llm.Message("user", args.text, images=images),
    ]
    try:
        for chunk in provider.chat(messages, stream=not args.no_stream):
            if chunk.type == "text":
                print(chunk.text, end="", flush=True)
            elif chunk.type == "usage" and args.verbose:
                print(f"\nusage: {chunk.usage}", file=sys.stderr)
    except llm.ProviderError as exc:
        print(f"\nprovider failed: {exc}", file=sys.stderr)
        return 1
    print()
    return 0


def _render_sessions(target: str, demo: bool = False) -> int:
    from .runtime import ensure_gdk_backend

    ensure_gdk_backend()
    from .store import session as session_store
    from .ui import sessions as sessions_ui
    from .ui.snapshot import offscreen_pixbuf, save_pixbuf

    pane = sessions_ui.SessionsPane(lambda *_: None, lambda: None)
    pane.sessions = sessions_ui.demo_sessions() if demo else session_store.list_sessions()
    if not pane.sessions:
        pane.sessions = sessions_ui.demo_sessions()
    pane._refill()
    pixbuf = offscreen_pixbuf(pane, 380, 460)
    print(f"render written: {save_pixbuf(pixbuf, target)}")
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    import json

    from .store import config, session as session_store

    action = args.action
    if action == "list" and args.render:
        return _render_sessions(args.render, demo=args.demo)

    if action == "list":
        items = session_store.list_sessions(limit=args.limit)
        if args.json:
            print(json.dumps([item.to_dict() for item in items], indent=2))
            return 0
        if not items:
            print("no sessions yet")
            return 0
        for item in items:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.updated_at))
            print(
                f"{item.id}  {stamp}  {len(item.captures):>2} cuts  "
                f"{item.turn_count():>2} asks  {item.title}"
            )
        return 0

    if action == "new":
        settings = config.load_settings()
        session = session_store.create_session(settings, title=args.title or "New session")
        session.save()
        print(session.id)
        return 0

    if action == "show":
        session = session_store.Session.load(args.id)
        if session is None:
            print(f"no session {args.id}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(session.to_dict(), indent=2))
            return 0
        print(f"{session.title}  ({session.id})")
        print(f"{len(session.captures)} cuts, {session.turn_count()} asks, {session.provider or 'no provider'}")
        for turn in session.turns:
            who = "you" if turn.role == "user" else "chinchilla"
            print(f"\n{who}: {turn.text}")
        return 0

    if action == "delete":
        session = session_store.Session.load(args.id)
        if session is None:
            print(f"no session {args.id}", file=sys.stderr)
            return 1
        session.delete()
        print(f"deleted {args.id}")
        return 0

    print(f"unknown action {action}", file=sys.stderr)
    return 2


def _render_settings(settings, page: int, target: str) -> int:
    """Show the dialog on the X11 backend and capture the requested tab.

    An offscreen window paints once, so it cannot capture a tab switch; a real
    window repaints like the app does.
    """
    from .runtime import ensure_gdk_backend

    ensure_gdk_backend()
    from .ui import settings as settings_ui
    from .ui.gtk import GLib, Gtk
    from .ui.snapshot import save_window_snapshot

    window = settings_ui.SettingsWindow(settings)
    window.show_all()

    def select() -> bool:
        window.content.set_current_page(page)
        return False

    def shoot() -> bool:
        ok = save_window_snapshot(window, target)
        print(f"render {'written' if ok else 'failed'}: {target}")
        Gtk.main_quit()
        return False

    GLib.timeout_add(600, select)
    GLib.timeout_add(1400, shoot)
    Gtk.main()
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    from .runtime import ensure_gdk_backend

    ensure_gdk_backend()
    from .store import config
    from .ui import settings as settings_ui

    settings = config.load_settings()
    if args.render:
        return _render_settings(settings, args.page, args.render)

    from .ui.gtk import Gtk

    window = settings_ui.SettingsWindow(settings)
    window.connect("destroy", lambda *_: Gtk.main_quit())
    window.show_all()
    Gtk.main()
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    from .ui.app import run_app

    return run_app([])


def cmd_daemon(args: argparse.Namespace) -> int:
    from .ui.app import run_app

    return run_app([], capture=False)


def cmd_shortcuts(args: argparse.Namespace) -> int:
    from . import shortcuts

    try:
        if args.action == "install":
            status = shortcuts.install(args.command, args.binding)
        elif args.action == "uninstall":
            status = shortcuts.uninstall()
        else:
            status = shortcuts.status()
    except shortcuts.ShortcutError as exc:
        print(f"shortcut error: {exc}", file=sys.stderr)
        return 1
    print(status.summary)
    if args.action == "install" and status.installed:
        print("log out and back in if the shortcut does not fire")
    return 0 if (status.installed or args.action == "uninstall") else 1


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
    capture_parser.add_argument("--panel", action="store_true", help="open the panel for the capture")
    capture_parser.set_defaults(func=cmd_capture)

    ask_parser = sub.add_parser("ask", help="send one prompt to the configured provider")
    ask_parser.add_argument("text")
    ask_parser.add_argument("--image", help="attach an image file")
    ask_parser.add_argument("--no-stream", action="store_true")
    ask_parser.add_argument("-v", "--verbose", action="store_true")
    ask_parser.set_defaults(func=cmd_ask)

    sessions_parser = sub.add_parser("sessions", help="list, create or inspect sessions")
    sessions_parser.add_argument("action", choices=["list", "new", "show", "delete"])
    sessions_parser.add_argument("id", nargs="?", help="session id")
    sessions_parser.add_argument("--title", help="title for a new session")
    sessions_parser.add_argument("--limit", type=int, default=20)
    sessions_parser.add_argument("--json", action="store_true")
    sessions_parser.add_argument("--render", help="render the session selector to a PNG")
    sessions_parser.add_argument("--demo", action="store_true", help="use sample rows when rendering")
    sessions_parser.set_defaults(func=cmd_sessions)

    app_parser = sub.add_parser("app", help="run the panel application (starts a capture)")
    app_parser.set_defaults(func=cmd_app)

    daemon_parser = sub.add_parser("daemon", help="run in the background with a tray icon")
    daemon_parser.set_defaults(func=cmd_daemon)

    shortcuts_parser = sub.add_parser(
        "shortcuts", help="install or inspect the GNOME keybinding"
    )
    shortcuts_parser.add_argument("action", nargs="?", choices=["status", "install", "uninstall"], default="status")
    shortcuts_parser.add_argument("--binding", default=DEFAULT_BINDING, help="accelerator to bind")
    shortcuts_parser.add_argument("--command", help="command to run (defaults to this installation)")
    shortcuts_parser.set_defaults(func=cmd_shortcuts)

    settings_parser = sub.add_parser("settings", help="open the settings dialog")
    settings_parser.add_argument("--render", help="render the dialog to a PNG and exit")
    settings_parser.add_argument("--page", type=int, default=0, help="tab index to render")
    settings_parser.set_defaults(func=cmd_settings)

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
    from . import log

    log.get("cli").info("invoked: %s", " ".join(sys.argv[1:] if argv is None else argv))
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
