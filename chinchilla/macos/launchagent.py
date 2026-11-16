"""Login agent that keeps the Chinchilla process (and its hotkey) running.

On GNOME a keybinding runs a command; on macOS the app has to be alive to own
the shortcut, so `shortcuts install` writes a LaunchAgent that starts
`chinchilla daemon` at login and loads it right away.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths

LABEL = "io.github.chinchilla"
# launchd starts agents with /usr/bin:/bin:/usr/sbin:/sbin only; these are
# where Homebrew and a manual Node usually live
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin")
# CA bundles for TLS-inspecting networks; the agent does not see shell exports
CARRIED_ENV = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")


class LaunchAgentError(RuntimeError):
    """`launchctl` is missing or refused the change."""


@dataclass
class AgentState:
    installed: bool
    loaded: bool
    running: bool = False
    pid: int | None = None
    program: list[str] | None = None


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def build_plist(program: list[str], env_path: str | None = None) -> dict:
    """The agent definition; `program` is the daemon command line."""
    entries = [part for part in (env_path or os.environ.get("PATH", "")).split(os.pathsep) if part]
    for folder in EXTRA_PATH:
        if folder not in entries:
            entries.append(folder)
    for folder in ("/usr/bin", "/bin", "/usr/sbin", "/sbin"):
        if folder not in entries:
            entries.append(folder)
    log = str(paths.state_dir() / "launchd.log")
    environment = {"PATH": os.pathsep.join(entries)}
    for name in CARRIED_ENV:
        if os.environ.get(name):
            environment[name] = os.environ[name]
    return {
        "Label": LABEL,
        "ProgramArguments": list(program),
        "RunAtLoad": True,
        # restart after a crash, stay down after Quit from the menu bar icon
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Interactive",
        "LimitLoadToSessionType": "Aqua",
        "EnvironmentVariables": environment,
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def _launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["launchctl", *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LaunchAgentError(str(exc)) from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise LaunchAgentError(detail or f"launchctl {args[0]} exited with {result.returncode}")
    return result


def read_program() -> list[str] | None:
    try:
        with plist_path().open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    program = data.get("ProgramArguments")
    return [str(part) for part in program] if isinstance(program, list) else None


def state() -> AgentState:
    installed = plist_path().is_file()
    program = read_program() if installed else None
    try:
        result = _launchctl("print", f"{_domain()}/{LABEL}", check=False)
    except LaunchAgentError:
        return AgentState(installed, False, program=program)
    if result.returncode != 0:
        return AgentState(installed, False, program=program)
    running, pid = False, None
    for raw in result.stdout.splitlines():
        # only the job's own keys, one tab deep; nested blocks (endpoints,
        # event sources) carry their own `state = active`
        if not raw.startswith("\t") or raw.startswith("\t\t"):
            continue
        line = raw.strip()
        if line.startswith("state = "):
            running = line == "state = running"
        elif line.startswith("pid = "):
            try:
                pid = int(line.split("=", 1)[1])
            except ValueError:
                pid = None
    return AgentState(installed, True, running, pid, program)


def unload() -> None:
    _launchctl("bootout", f"{_domain()}/{LABEL}", check=False)


def kickstart(restart: bool = False) -> None:
    """Start the loaded job now (`restart` kills a running one first)."""
    args = ["kickstart", *(["-k"] if restart else []), f"{_domain()}/{LABEL}"]
    _launchctl(*args)


def install(program: list[str]) -> AgentState:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_dir().mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(build_plist(program), handle)
    unload()
    # bootout returns before the old job is gone; bootstrap answers EIO until then
    for attempt in range(10):
        try:
            _launchctl("bootstrap", _domain(), str(path))
            break
        except LaunchAgentError:
            if attempt == 9:
                raise
            time.sleep(0.5)
    return state()


def uninstall() -> AgentState:
    unload()
    plist_path().unlink(missing_ok=True)
    return AgentState(False, False)
