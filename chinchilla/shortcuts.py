"""The global capture shortcut.

GNOME: a custom keybinding in `gsettings` that runs `chinchilla capture
--panel`. macOS: there is no keybinding daemon to hand a command to, so a login
agent keeps `chinchilla daemon` running and that process owns the hotkey
(`chinchilla/macos/hotkey.py`); the binding itself lives in `settings.json`.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass

from . import system

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
        if self.detail:
            return f"{self.binding} -> {self.command} ({self.detail})"
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
    if system.is_mac():
        return shutil.which("launchctl") is not None
    return shutil.which("gsettings") is not None


def status() -> ShortcutStatus:
    if system.is_mac():
        return _mac_status()
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
    if system.is_mac():
        return _mac_install(command, binding)
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
    reload()
    return ShortcutStatus(True, True, binding=binding, command=command)


def reload() -> None:
    """Drop and re-add the slot so the keybinding daemon reads it again.

    `gsd-media-keys` registers a custom shortcut when the slot appears in the
    list; editing the slot afterwards is not always picked up, which leaves a
    keybinding that silently does nothing.
    """
    if system.is_mac():
        _mac_restart()
        return
    if not available():
        raise ShortcutError("gsettings not found")
    paths = parse_keybindings(_gsettings("get", MEDIA_KEYS, "custom-keybindings"))
    if BASE_PATH not in paths:
        return
    without = [path for path in paths if path != BASE_PATH]
    _gsettings("set", MEDIA_KEYS, "custom-keybindings", format_keybindings(without))
    _gsettings("set", MEDIA_KEYS, "custom-keybindings", format_keybindings(paths))


def uninstall() -> ShortcutStatus:
    if system.is_mac():
        return _mac_uninstall()
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

# ---------------------------------------------------------------------- macOS


def mac_daemon_command() -> list[str]:
    """The login agent runs the daemon with this exact interpreter."""
    return [sys.executable, "-m", "chinchilla", "daemon"]


def _mac_binding() -> str:
    from .store import config

    return config.load_settings().hotkey or DEFAULT_BINDING


def _mac_status() -> ShortcutStatus:
    from .macos import launchagent

    if not available():
        return ShortcutStatus(False, False, detail="launchctl not found")
    state = launchagent.state()
    command = " ".join(state.program or [])
    if not state.installed:
        return ShortcutStatus(True, False, detail="no login agent")
    if not state.loaded:
        return ShortcutStatus(
            True, False, binding=_mac_binding(), command=command,
            detail="login agent written but not loaded: chinchilla shortcuts install",
        )
    detail = f"running, pid {state.pid}" if state.running else "loaded, not running"
    return ShortcutStatus(True, True, binding=_mac_binding(), command=command, detail=detail)


def _mac_install(command: str | None, binding: str) -> ShortcutStatus:
    from .macos import hotkey, launchagent
    from .store import config

    if not available():
        raise ShortcutError("launchctl not found")
    try:
        hotkey.parse(binding)
    except hotkey.HotkeyError as exc:
        raise ShortcutError(str(exc)) from exc
    settings = config.load_settings()
    if settings.hotkey != binding:
        settings.hotkey = binding
        config.save_settings(settings)
    program = shlex.split(command) if command else mac_daemon_command()
    try:
        launchagent.install(program)
    except launchagent.LaunchAgentError as exc:
        raise ShortcutError(f"cannot load the login agent: {exc}") from exc
    return _mac_status()


def _mac_restart() -> None:
    from .macos import launchagent

    try:
        launchagent.kickstart(restart=True)
    except launchagent.LaunchAgentError as exc:
        raise ShortcutError(str(exc)) from exc


def _mac_uninstall() -> ShortcutStatus:
    from .macos import launchagent

    if not available():
        raise ShortcutError("launchctl not found")
    launchagent.uninstall()
    return ShortcutStatus(True, False, detail="removed")
