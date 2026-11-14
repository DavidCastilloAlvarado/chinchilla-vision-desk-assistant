"""Screen capture backends.

Wayland forbids reading the screen directly, so every backend is a portal, a
desktop helper or an X11 grab. They are tried in order and the first one that
produces pixels wins. Area backends hand back an already cropped image.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from .. import log
from .geometry import Rect, fit

LOGGER = log.get("capture")
PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SHELL_NAME = "org.gnome.Shell.Screenshot"
SHELL_PATH = "/org/gnome/Shell/Screenshot"
PORTAL_TIMEOUT = 30.0


class CaptureError(RuntimeError):
    """Raised when a backend cannot deliver an image."""


@dataclass
class Grab:
    image: Image.Image
    backend: str
    crop: Rect | None = None
    screen_size: tuple[int, int] | None = None


@dataclass
class Backend:
    id: str
    kind: str  # "screen" or "area"
    description: str
    probe: Callable[[], tuple[bool, str]]
    grab: Callable[[], Image.Image]


# --------------------------------------------------------------------- helpers


def _gi():
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    return Gio, GLib


def _bus_has_owner(name: str) -> bool:
    try:
        Gio, GLib = _gi()
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = conn.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (name,)),
            None,
            Gio.DBusCallFlags.NONE,
            3000,
            None,
        )
        return bool(reply.unpack()[0])
    except Exception:  # pragma: no cover - no session bus
        return False


def _file_uri_to_path(uri: str) -> Path:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise CaptureError(f"portal returned a non file uri: {uri}")
    return Path(unquote(parsed.path))


def _run(command: list[str], path_hint: str | None = None) -> Image.Image:
    result = subprocess.run(command, capture_output=True, timeout=25)
    if result.returncode != 0:
        raise CaptureError(
            f"{command[0]} failed ({result.returncode}): "
            f"{result.stderr.decode(errors='replace').strip()[:200]}"
        )
    if path_hint:
        return Image.open(path_hint).copy()
    return Image.open(io.BytesIO(result.stdout)).copy()


# ---------------------------------------------------------------------- portal


_parent_window = ""


def set_parent_window(handle: str | None) -> None:
    """Remembers the X11 handle the portal should parent its dialog to."""
    global _parent_window
    _parent_window = handle or ""


def parent_window() -> str:
    return _parent_window


def _portal_screenshot(
    interactive: bool = False, timeout: float = PORTAL_TIMEOUT, parent: str = ""
) -> Path:
    Gio, GLib = _gi()
    from gi.repository import GLib as _GLib

    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    sender = conn.get_unique_name().lstrip(":").replace(".", "_")
    token = f"chinchilla_{os.getpid()}_{int(time.time() * 1000) % 100000}"
    handle = f"{PORTAL_PATH}/request/{sender}/{token}"
    loop = GLib.MainLoop()
    state: dict[str, object] = {}

    def on_response(_conn, _sender, _path, _iface, _signal, params, _data):
        code, results = params.unpack()
        state["code"] = code
        state["uri"] = results.get("uri")
        loop.quit()

    subscription = conn.signal_subscribe(
        PORTAL_NAME,
        "org.freedesktop.portal.Request",
        "Response",
        handle,
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
        None,
    )
    options = {
        "handle_token": _GLib.Variant("s", token),
        "interactive": _GLib.Variant("b", interactive),
        # A modal request is what makes GNOME show its permission prompt
        # instead of refusing outright.
        "modal": _GLib.Variant("b", True),
    }
    try:
        reply = conn.call_sync(
            PORTAL_NAME,
            PORTAL_PATH,
            "org.freedesktop.portal.Screenshot",
            "Screenshot",
            _GLib.Variant("(sa{sv})", (parent or _parent_window, options)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
        )
    except Exception as exc:
        raise CaptureError(f"portal call failed: {exc}") from exc

    returned = reply.unpack()[0]
    if returned and returned != handle:  # pragma: no cover - defensive
        conn.signal_unsubscribe(subscription)
        subscription = conn.signal_subscribe(
            PORTAL_NAME,
            "org.freedesktop.portal.Request",
            "Response",
            returned,
            None,
            Gio.DBusSignalFlags.NONE,
            on_response,
            None,
        )

    def bail() -> bool:
        state["timeout"] = True
        loop.quit()
        return False

    timer = GLib.timeout_add(int(timeout * 1000), bail)
    loop.run()
    GLib.source_remove(timer)
    conn.signal_unsubscribe(subscription)

    if state.get("timeout"):
        raise CaptureError(
            "portal did not answer in time; a permission dialog may be waiting"
        )
    code = state.get("code")
    if code == 1:
        raise CaptureError("portal capture cancelled")
    if code != 0 or not state.get("uri"):
        raise CaptureError(
            "portal refused the screenshot; grant the screenshot permission "
            "for this app or pick another backend"
        )
    return _file_uri_to_path(str(state["uri"]))


def _grab_portal() -> Image.Image:
    path = _portal_screenshot(interactive=False)
    try:
        return Image.open(path).copy()
    finally:
        path.unlink(missing_ok=True)


def _grab_portal_area() -> Image.Image:
    path = _portal_screenshot(interactive=True)
    try:
        return Image.open(path).copy()
    finally:
        path.unlink(missing_ok=True)


def _probe_portal() -> tuple[bool, str]:
    if not _bus_has_owner(PORTAL_NAME):
        return False, "xdg-desktop-portal is not running"
    return True, "xdg-desktop-portal Screenshot"


def _probe_portal_area() -> tuple[bool, str]:
    ok, detail = _probe_portal()
    return ok, detail + " (area)"

def _grab_shell() -> Image.Image:
    Gio, GLib = _gi()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        path = Path(handle.name)
    try:
        conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        conn.call_sync(
            SHELL_NAME,
            SHELL_PATH,
            SHELL_NAME,
            "Screenshot",
            GLib.Variant("(bbs)", (False, False, str(path))),
            None,
            Gio.DBusCallFlags.NONE,
            15000,
            None,
        )
        return Image.open(path).copy()
    finally:
        path.unlink(missing_ok=True)


def _probe_shell() -> tuple[bool, str]:
    if not _bus_has_owner(SHELL_NAME):
        return False, "org.gnome.Shell.Screenshot is not available"
    return True, "org.gnome.Shell.Screenshot"


def _cli_backend(
    backend_id: str, tool: str, command: list[str], area: bool = False
) -> Backend:
    def probe() -> tuple[bool, str]:
        path = shutil.which(tool)
        return (bool(path), path or f"{tool} not installed")

    def grab() -> Image.Image:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "capture.png"
            resolved = [part.replace("{out}", str(target)) for part in command]
            if "{out}" in " ".join(command):
                return _run(resolved, path_hint=str(target))
            return _run(resolved)

    kind = "area" if area else "screen"
    return Backend(backend_id, kind, f"{tool} command line", probe, grab)


def _probe_file() -> tuple[bool, str]:
    source = os.environ.get("CHINCHILLA_CAPTURE_SOURCE")
    if source and Path(source).is_file():
        return True, f"CHINCHILLA_CAPTURE_SOURCE={source}"
    return False, "CHINCHILLA_CAPTURE_SOURCE is not set"


def _grab_file() -> Image.Image:
    source = os.environ.get("CHINCHILLA_CAPTURE_SOURCE")
    if not source or not Path(source).is_file():
        raise CaptureError("CHINCHILLA_CAPTURE_SOURCE does not point to a file")
    return Image.open(source).copy()


def _probe_x11() -> tuple[bool, str]:
    if os.environ.get("WAYLAND_DISPLAY"):
        return False, "X11 grab cannot see a Wayland desktop"
    if not os.environ.get("DISPLAY"):
        return False, "no DISPLAY"
    return True, "X11 root window"


def _grab_x11() -> Image.Image:
    from PIL import ImageGrab

    return ImageGrab.grab(all_screens=True)


# --------------------------------------------------------------------- catalog


def backends() -> list[Backend]:
    catalog = [
        Backend("file", "screen", "image from CHINCHILLA_CAPTURE_SOURCE", _probe_file, _grab_file),
        Backend("portal", "screen", "XDG portal (full screen)", _probe_portal, _grab_portal),
        Backend("portal-area", "area", "XDG portal (select area)", _probe_portal_area, _grab_portal_area),
        Backend("gnome-shell", "screen", "GNOME Shell screenshot", _probe_shell, _grab_shell),
        _cli_backend("grim", "grim", ["grim", "-t", "png", "-"]),
        _cli_backend("gnome-screenshot", "gnome-screenshot", ["gnome-screenshot", "-f", "{out}"]),
        _cli_backend("spectacle", "spectacle", ["spectacle", "-b", "-n", "-o", "{out}"]),
        _cli_backend("scrot", "scrot", ["scrot", "-o", "{out}"]),
        _cli_backend("import", "import", ["import", "-window", "root", "{out}"]),
        Backend("x11", "screen", "X11 root window", _probe_x11, _grab_x11),
    ]
    return catalog


def describe_backends() -> list[str]:
    lines = []
    for backend in backends():
        ok, detail = backend.probe()
        lines.append(f"{'ok  ' if ok else 'fail'} {backend.id:<17} {backend.kind:<6} {detail}")
    return lines


def probe_backends() -> tuple[list[str], list[str]]:
    available, details = [], []
    for backend in backends():
        ok, detail = backend.probe()
        if ok:
            available.append(backend.id)
        details.append(f"{backend.id}: {detail}")
    return available, details


def available_backends(kind: str | None = None) -> list[Backend]:
    result = []
    for backend in backends():
        if kind and backend.kind != kind:
            continue
        ok, _detail = backend.probe()
        if ok:
            result.append(backend)
    return result


def grab_screen(preferred: str | None = None, parent: str | None = None) -> Grab:
    """Full screen image from the first backend that works.

    `parent` is the X11 handle of the window asking for the grab: the portal
    attaches its permission dialog to it, which GNOME requires before it lets
    the dialog appear.
    """
    set_parent_window(parent)
    candidates = available_backends("screen")
    if preferred:
        candidates.sort(key=lambda backend: backend.id != preferred)
    errors = []
    for backend in candidates:
        started = time.monotonic()
        try:
            image = backend.grab()
        except Exception as exc:
            LOGGER.warning("backend %s failed: %s", backend.id, exc)
            errors.append(f"{backend.id}: {exc}")
            continue
        LOGGER.info(
            "captured %sx%s with %s in %.0f ms",
            image.width,
            image.height,
            backend.id,
            (time.monotonic() - started) * 1000,
        )
        return Grab(image=image, backend=backend.id)
    detail = "; ".join(errors) if errors else "no capture backend is available"
    raise CaptureError(detail)


def grab_area(preferred: str | None = None) -> Grab:
    """Cropped image from an area backend (the desktop's own selector)."""
    candidates = available_backends("area")
    if preferred:
        candidates.sort(key=lambda backend: backend.id != preferred)
    errors = []
    for backend in candidates:
        try:
            image = backend.grab()
        except Exception as exc:
            errors.append(f"{backend.id}: {exc}")
            continue
        return Grab(image=image, backend=backend.id)
    detail = "; ".join(errors) if errors else "no area capture backend is available"
    raise CaptureError(detail)


# ------------------------------------------------------------------- encoding


def crop(image: Image.Image, rect: Rect, screen_size: tuple[int, int]) -> Image.Image:
    """Crop using overlay coordinates, which live in screen space."""
    scale_x = image.width / screen_size[0]
    scale_y = image.height / screen_size[1]
    box = (
        max(0, int(rect.x * scale_x)),
        max(0, int(rect.y * scale_y)),
        min(image.width, int(round(rect.right * scale_x))),
        min(image.height, int(round(rect.bottom * scale_y))),
    )
    return image.crop(box)


def limit(image: Image.Image, max_side: int = 1400) -> Image.Image:
    longest = max(image.width, image.height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def encode_jpeg(image: Image.Image, max_side: int = 1400, quality: int = 84) -> bytes:
    buffer = io.BytesIO()
    limit(image.convert("RGB"), max_side).save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def save_jpeg(image: Image.Image, path: str | Path, max_side: int = 1600) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode_jpeg(image, max_side=max_side))
    return target


# Kept for callers that need the rect of a scaled image.
def rect_in(image: Image.Image, rect: Rect, screen_size: tuple[int, int]) -> Rect:
    return fit(
        Rect(
            int(rect.x * image.width / screen_size[0]),
            int(rect.y * image.height / screen_size[1]),
            int(rect.width * image.width / screen_size[0]),
            int(rect.height * image.height / screen_size[1]),
        )
    )
