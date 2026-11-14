"""GNOME custom keybindings for the global capture shortcut."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_KEYBINDING = MEDIA_KEYS + ".custom-keybinding"
SLOT = "chinchilla"
BASE_PATH = f"/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/{SLOT}/"
DEFAULT_BINDING = "<Control><Alt>a"
DEFAULT_NAME = "Chinchilla capture"
DEFAULT_COMMAND = "chinchilla capture --panel"


class ShortcutError(RuntimeError):
    """`gsettings` is missing or refused the change."""


@dataclass
class ShortcutStatus:
    available: bool
    installed: bool
    binding: str = ""
    command: str = ""
    detail: str = ""

    @property
    def summary(self) -> str:
        if not self.available:
            return self.detail or "gsettings not available"
        if not self.installed:
            return "not installed"
        return f"{self.binding} -> {self.command}"


def _gsettings(*args: str) -> str:
    binary = shutil.which("gsettings")
    if binary is None:
        raise ShortcutError("gsettings not found")
    try:
        result = subprocess.run(
            [binary, *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ShortcutError(str(exc)) from exc
    if result.returncode != 0:
        raise ShortcutError(result.stderr.strip() or "gsettings exited with an error")
    return result.stdout.strip()


def parse_keybindings(raw: str) -> list[str]:
    """Read a gsettings string list such as ``['/a/', '/b/']``."""
    return re.findall(r"'([^']*)'", raw or "")


def format_keybindings(paths: list[str]) -> str:
    return "[" + ", ".join(f"'{path}'" for path in paths) + "]"


def default_command() -> str:
    """The shortcut has to work without the virtualenv on PATH."""
    installed = shutil.which("chinchilla")
    if installed:
        return f"{installed} capture --panel"
    return f"{sys.executable} -m chinchilla capture --panel"


def available() -> bool:
    return shutil.which("gsettings") is not None


def status() -> ShortcutStatus:
    if not available():
        return ShortcutStatus(False, False, detail="gsettings not found")
    try:
        paths = parse_keybindings(_gsettings("get", MEDIA_KEYS, "custom-keybindings"))
    except ShortcutError as exc:
        return ShortcutStatus(True, False, detail=str(exc))
    if BASE_PATH not in paths:
        return ShortcutStatus(True, False, detail="no chinchilla keybinding")
    schema = f"{CUSTOM_KEYBINDING}:{BASE_PATH}"
    try:
        binding = _gsettings("get", schema, "binding").strip("'")
        command = _gsettings("get", schema, "command").strip("'")
    except ShortcutError as exc:
        return ShortcutStatus(True, False, detail=str(exc))
    return ShortcutStatus(True, True, binding=binding, command=command)


def install(
    command: str | None = None,
    binding: str = DEFAULT_BINDING,
    name: str = DEFAULT_NAME,
) -> ShortcutStatus:
    """Register the slot in GNOME's custom keybindings list."""
    command = command or default_command()
    if not available():
        raise ShortcutError("gsettings not found; install it or add the shortcut by hand")
    paths = parse_keybindings(_gsettings("get", MEDIA_KEYS, "custom-keybindings"))
    if BASE_PATH not in paths:
        paths.append(BASE_PATH)
        try:
            _gsettings("set", MEDIA_KEYS, "custom-keybindings", format_keybindings(paths))
        except ShortcutError as exc:
            raise ShortcutError(f"cannot update the keybinding list: {exc}") from exc
    schema = f"{CUSTOM_KEYBINDING}:{BASE_PATH}"
    _gsettings("set", schema, "name", name)
    _gsettings("set", schema, "command", command)
    _gsettings("set", schema, "binding", binding)
    return ShortcutStatus(True, True, binding=binding, command=command)


def uninstall() -> ShortcutStatus:
    if not available():
        raise ShortcutError("gsettings not found")
    paths = parse_keybindings(_gsettings("get", MEDIA_KEYS, "custom-keybindings"))
    if BASE_PATH in paths:
        paths = [path for path in paths if path != BASE_PATH]
        _gsettings("set", MEDIA_KEYS, "custom-keybindings", format_keybindings(paths))
    try:
        _gsettings("reset", f"{CUSTOM_KEYBINDING}:{BASE_PATH}", "name")
        _gsettings("reset", f"{CUSTOM_KEYBINDING}:{BASE_PATH}", "command")
        _gsettings("reset", f"{CUSTOM_KEYBINDING}:{BASE_PATH}", "binding")
    except ShortcutError:
        pass
    return ShortcutStatus(True, False, detail="removed")