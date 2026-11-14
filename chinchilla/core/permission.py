"""Screenshot permission for the xdg-desktop-portal.

GNOME only answers a silent (non interactive) screenshot when the calling app
already owns the ``screenshot`` permission. The portal derives the app id from
the systemd scope, so Chinchilla looks up its own id and records the grant
once; after that ``Ctrl+Alt+A`` captures without a dialog and without the
desktop's own selector.
"""

from __future__ import annotations

import re

from .. import log

LOGGER = log.get("permission")

STORE_NAME = "org.freedesktop.impl.portal.PermissionStore"
STORE_PATH = "/org/freedesktop/impl/portal/PermissionStore"
STORE_IFACE = "org.freedesktop.impl.portal.PermissionStore"
TABLE = "screenshot"
ENTRY = "screenshot"
GRANTED = "yes"
CGROUP_PATH = "/proc/self/cgroup"

_SCOPE = re.compile(r"app-(?P<id>.+)-\d+\.scope")
_ESCAPED = re.compile(r"\\x([0-9a-fA-F]{2})")


class PermissionError_(RuntimeError):
    """Raised when the permission store cannot be queried."""


def _unescape(value: str) -> str:
    return _ESCAPED.sub(lambda m: chr(int(m.group(1), 16)), value)


def app_id(cgroup: str | None = None) -> str:
    """The id the portal will use for this process (empty without a scope)."""
    if cgroup is None:
        try:
            with open(CGROUP_PATH, encoding="utf-8") as handle:
                cgroup = handle.read()
        except OSError:
            cgroup = ""
    match = _SCOPE.search((cgroup or "").strip())
    return _unescape(match.group("id")) if match else ""


def _gio():
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    return Gio, GLib


def _call(method: str, signature: str, args: tuple, timeout_ms: int = 3000):
    Gio, GLib = _gio()
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    return conn.call_sync(
        STORE_NAME,
        STORE_PATH,
        STORE_IFACE,
        method,
        GLib.Variant(signature, args),
        None,
        Gio.DBusCallFlags.NONE,
        timeout_ms,
        None,
    )


def permissions(target: str | None = None) -> list[str]:
    """The stored permissions for our app id; empty when never answered."""
    name = app_id() if target is None else target
    try:
        reply = _call("Lookup", "(ss)", (TABLE, ENTRY))
    except Exception as exc:
        raise PermissionError_(f"cannot read the portal permission store: {exc}") from exc
    entries = reply.unpack()[0]
    return list(entries.get(name, []))


def is_granted(target: str | None = None) -> bool:
    try:
        return GRANTED in permissions(target)
    except PermissionError_:
        return False


def grant(target: str | None = None) -> bool:
    """Records the screenshot grant for our app id."""
    name = app_id() if target is None else target
    try:
        _call("SetPermission", "(sbssas)", (TABLE, True, ENTRY, name, [GRANTED]))
    except Exception as exc:
        LOGGER.warning("cannot grant the screenshot permission: %s", exc)
        return False
    LOGGER.info("screenshot permission granted for app id %r", name)
    return True


def revoke(target: str | None = None) -> bool:
    """Forgets the grant so the next capture asks the desktop again."""
    name = app_id() if target is None else target
    try:
        _call("DeletePermission", "(sbs)", (TABLE, ENTRY, name))
    except Exception as exc:
        LOGGER.warning("cannot revoke the screenshot permission: %s", exc)
        return False
    LOGGER.info("screenshot permission revoked for app id %r", name)
    return True


def ensure() -> tuple[bool, str]:
    """Makes sure a silent screenshot is allowed; returns (ok, detail)."""
    name = app_id()
    try:
        stored = permissions()
    except PermissionError_ as exc:
        return False, str(exc)
    if GRANTED in stored:
        return True, f"granted for {name!r}"
    if not grant():
        return False, f"cannot grant the screenshot permission for {name!r}"
    return True, f"granted for {name!r}"


def describe() -> str:
    name = app_id()
    try:
        stored = permissions()
    except PermissionError_ as exc:
        return str(exc)
    state = "granted" if GRANTED in stored else "missing"
    return f"{state} (app id {name!r})"