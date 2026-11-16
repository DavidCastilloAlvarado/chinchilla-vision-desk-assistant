"""Single instance over a Unix socket.

On Linux `Gtk.Application` is unique through the session D-Bus, so a second
`chinchilla capture --panel` only activates the running process. macOS has no
session bus, GApplication silently runs every launch as a new process, and two
of them would fight over the hotkey and draw two menu bar icons. The first
process listens on `paths.socket_path()`; later launches hand it their request
and exit.
"""

from __future__ import annotations

import fcntl
import os
import socket
from pathlib import Path
from typing import Callable

from . import log, paths

LOGGER = log.get("instance")
COMMANDS = ("capture", "show", "daemon")
TIMEOUT = 2.0


def forward(command: str, path: Path | None = None) -> bool:
    """True when a running instance took `command`.

    A refused connection means a stale socket. Once connected the request sits
    in the socket until that instance's main loop reads it, so a slow reply
    (a busy loop) still counts as delivered.
    """
    target = path or paths.socket_path()
    if not target.exists():
        return False
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(TIMEOUT)
        try:
            client.connect(str(target))
            client.sendall(command.encode() + b"\n")
        except OSError as exc:
            LOGGER.info("no running instance at %s: %s", target, exc)
            return False
        try:
            reply = client.recv(16)
        except OSError:
            LOGGER.info("the running instance is busy; %r is queued", command)
            return True
    return reply.strip() == b"ok"


class Listener:
    """Accepts commands from later launches inside the GLib main loop."""

    def __init__(self, on_command: Callable[[str], None], path: Path | None = None) -> None:
        self.on_command = on_command
        self.path = path or paths.socket_path()
        # True when another live process holds the instance lock
        self.taken = False
        self._lock = None
        self._server: socket.socket | None = None
        self._watch: int | None = None

    def _claim(self) -> bool:
        """An exclusive lock for the life of the process decides who owns the socket.

        Probing the socket alone races: two launches can both find it silent
        and the second would unlink the first one's live socket.
        """
        lock_path = self.path.with_name(self.path.name + ".lock")
        handle = open(lock_path, "a+")
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            self.taken = True
            return False
        self._lock = handle
        return True

    def _release(self) -> None:
        if self._lock is not None:
            self._lock.close()  # closing drops the flock
            self._lock = None

    def start(self) -> bool:
        from gi.repository import GLib

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self._claim():
            LOGGER.warning("another instance owns %s", self.path)
            return False
        # we hold the lock, so whatever file is there was left by a crash
        self.path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.path))
            os.chmod(self.path, 0o600)
            server.listen(16)
        except OSError as exc:
            LOGGER.warning("cannot listen on %s: %s", self.path, exc)
            server.close()
            self._release()
            return False
        server.setblocking(False)
        self._server = server
        self._watch = GLib.io_add_watch(
            server.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._accept
        )
        LOGGER.info("listening on %s", self.path)
        return True

    def _accept(self, _fd, _condition) -> bool:
        if self._server is None:
            return False
        try:
            connection, _address = self._server.accept()
        except OSError:
            return True
        with connection:
            connection.settimeout(TIMEOUT)
            try:
                command = connection.recv(64).decode(errors="replace").strip()
                known = command in COMMANDS
                connection.sendall(b"ok\n" if known else b"unknown\n")
            except OSError as exc:
                LOGGER.warning("bad request on the control socket: %s", exc)
                return True
        if known:
            LOGGER.info("command from another launch: %s", command)
            self.on_command(command)
        return True

    def stop(self) -> None:
        if self._watch is not None:
            from gi.repository import GLib

            GLib.source_remove(self._watch)
            self._watch = None
        if self._server is not None:
            self._server.close()
            self._server = None
            # unlink before the lock goes, so a newcomer never loses its socket
            self.path.unlink(missing_ok=True)
        self._release()
