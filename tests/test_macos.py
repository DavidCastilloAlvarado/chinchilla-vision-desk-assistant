"""macOS support that can be checked without touching the real desktop."""

import os
import plistlib
import stat
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from chinchilla import shortcuts, system
from chinchilla.core import capture, permission
from chinchilla.macos import hotkey, launchagent


@pytest.fixture()
def mac(monkeypatch):
    monkeypatch.setattr(system, "is_mac", lambda: True)


# ------------------------------------------------------------------- hotkey


def test_parse_the_default_binding():
    parsed = hotkey.parse("<Control><Alt>a")

    assert parsed.key_code == 0x00
    assert parsed.modifiers == hotkey.CONTROL | hotkey.OPTION
    assert parsed.label == "\u2303\u2325A"


def test_primary_is_command_and_case_is_ignored():
    parsed = hotkey.parse("<Primary><SHIFT>C")

    assert parsed.key_code == 0x08
    assert parsed.modifiers == hotkey.CMD | hotkey.SHIFT


@pytest.mark.parametrize(
    "accelerator, message",
    [
        ("<Hyper>a", "unknown modifier"),
        ("<Control>&", "unsupported key"),
        ("a", "needs at least one modifier"),
        ("", "unsupported key"),
    ],
)
def test_parse_rejects_what_carbon_cannot_bind(accelerator, message):
    with pytest.raises(hotkey.HotkeyError, match=message):
        hotkey.parse(accelerator)


# -------------------------------------------------------------- launch agent


def test_plist_runs_the_daemon_with_a_usable_path(xdg):
    data = launchagent.build_plist(
        ["/venv/bin/python", "-m", "chinchilla", "daemon"], env_path="/custom/node/bin"
    )

    assert data["Label"] == launchagent.LABEL
    assert data["ProgramArguments"] == ["/venv/bin/python", "-m", "chinchilla", "daemon"]
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] == {"SuccessfulExit": False}
    entries = data["EnvironmentVariables"]["PATH"].split(os.pathsep)
    assert entries[0] == "/custom/node/bin"
    assert "/opt/homebrew/bin" in entries and "/usr/bin" in entries
    assert data["StandardErrorPath"].endswith("launchd.log")
    plistlib.dumps(data)  # serialisable as is


def test_state_reads_launchctl_print(monkeypatch, tmp_path):
    plist = tmp_path / "agent.plist"
    plist.write_bytes(plistlib.dumps({"ProgramArguments": ["python", "-m", "chinchilla", "daemon"]}))
    monkeypatch.setattr(launchagent, "plist_path", lambda: plist)

    class Result:
        returncode = 0
        stdout = (
            "gui/501/io.github.chinchilla = {\n\tstate = running\n\tpid = 4242\n"
            "\tendpoints = {\n\t\tstate = active\n\t}\n}\n"
        )
        stderr = ""

    monkeypatch.setattr(launchagent, "_launchctl", lambda *args, check=True: Result())

    state = launchagent.state()

    assert state.installed and state.loaded and state.running
    assert state.pid == 4242
    assert state.program == ["python", "-m", "chinchilla", "daemon"]


def test_state_without_a_loaded_job(monkeypatch, tmp_path):
    monkeypatch.setattr(launchagent, "plist_path", lambda: tmp_path / "missing.plist")

    class Result:
        returncode = 113
        stdout = ""
        stderr = "Could not find service"

    monkeypatch.setattr(launchagent, "_launchctl", lambda *args, check=True: Result())

    state = launchagent.state()

    assert not state.installed and not state.loaded and not state.running


# ----------------------------------------------------------------- shortcuts


def test_mac_install_saves_the_binding_and_loads_the_agent(mac, xdg, monkeypatch):
    from chinchilla.store import config

    installed: dict[str, list[str]] = {}
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(launchagent, "install", lambda program: installed.setdefault("program", program))
    monkeypatch.setattr(
        launchagent,
        "state",
        lambda: launchagent.AgentState(True, True, True, 77, installed.get("program")),
    )

    status = shortcuts.install(None, "<Control><Shift>x")

    assert installed["program"] == [sys.executable, "-m", "chinchilla", "daemon"]
    assert config.load_settings().hotkey == "<Control><Shift>x"
    assert status.installed is True
    assert status.binding == "<Control><Shift>x"
    assert "running, pid 77" in status.summary


def test_mac_install_refuses_a_binding_carbon_cannot_register(mac, xdg, monkeypatch):
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: f"/bin/{name}")

    with pytest.raises(shortcuts.ShortcutError, match="needs at least one modifier"):
        shortcuts.install(None, "a")


def test_mac_status_without_the_agent(mac, xdg, monkeypatch):
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(launchagent, "state", lambda: launchagent.AgentState(False, False))

    status = shortcuts.status()

    assert status.available is True
    assert status.installed is False
    assert status.summary == "not installed"


# ---------------------------------------------------------------- permission


def test_mac_permission_uses_screen_recording(mac, monkeypatch):
    from chinchilla.macos import tcc

    monkeypatch.setattr(permission, "_mac_requested", False)

    granted = {"value": False}
    requested: list[bool] = []
    monkeypatch.setattr(tcc, "is_granted", lambda: granted["value"])
    monkeypatch.setattr(tcc, "request", lambda: requested.append(True) or False)

    ok, detail = permission.ensure()

    assert ok is False
    assert "Screen Recording" in detail
    assert requested == [True]
    assert permission.describe().startswith("missing (Screen Recording")
    # asked once per process: on a managed Mac the prompt wants an admin
    assert permission.ensure()[0] is False
    assert requested == [True]

    granted["value"] = True

    assert permission.ensure() == (True, "Screen Recording granted")
    assert permission.is_granted() is True
    assert permission.describe() == "granted (Screen Recording)"


def test_mac_revoke_opens_system_settings(mac, monkeypatch):
    from chinchilla.macos import tcc

    opened: list[bool] = []
    monkeypatch.setattr(tcc, "open_settings", lambda: opened.append(True) or True)

    assert permission.revoke() is False
    assert opened == [True]


# ------------------------------------------------------------------- capture


FAKE_SCREENCAPTURE = """#!{python}
import sys
from PIL import Image
args = sys.argv[1:]
if "-i" in args and "{cancel}" == "yes":
    sys.exit(0)
Image.new("RGB", (64, 32), (200, 10, 10)).save(args[-1])
"""


def _fake_screencapture(tmp_path, monkeypatch, cancel=False):
    binary = tmp_path / "bin" / "screencapture"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        FAKE_SCREENCAPTURE.format(python=sys.executable, cancel="yes" if cancel else "no"),
        encoding="utf-8",
    )
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{binary.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.delenv("CHINCHILLA_CAPTURE_SOURCE", raising=False)


def test_mac_catalog_only_has_screencapture(mac):
    assert [backend.id for backend in capture.backends()] == [
        "file",
        "screencapture",
        "screencapture-area",
        "clipboard",
    ]


def test_clipboard_waits_for_a_new_copy(monkeypatch):
    from chinchilla.macos import pasteboard

    counts = iter([7, 7, 7, 8])
    monkeypatch.setattr(pasteboard, "change_count", lambda: next(counts))
    monkeypatch.setattr(pasteboard, "read_image", lambda: Image.new("RGB", (30, 20)))
    monkeypatch.setattr(pasteboard, "POLL_SECONDS", 0)

    image = pasteboard.wait_for_image(5)

    assert image is not None and image.size == (30, 20)



def test_clipboard_wait_skips_a_text_copy(monkeypatch):
    from chinchilla.macos import pasteboard

    counts = iter([7, 8, 8, 9])
    images = iter([None, Image.new("RGB", (12, 8))])
    monkeypatch.setattr(pasteboard, "change_count", lambda: next(counts))
    monkeypatch.setattr(pasteboard, "read_image", lambda: next(images))
    monkeypatch.setattr(pasteboard, "POLL_SECONDS", 0)

    image = pasteboard.wait_for_image(5)

    assert image is not None and image.size == (12, 8)

def test_clipboard_gives_up_on_timeout(mac, monkeypatch):
    from chinchilla.macos import pasteboard

    monkeypatch.setattr(pasteboard, "change_count", lambda: 3)
    monkeypatch.setattr(pasteboard, "POLL_SECONDS", 0)

    with pytest.raises(capture.CaptureError, match="no image reached the clipboard"):
        capture.grab_clipboard(timeout=0.05)


def test_clipboard_backend_is_reached_by_name(mac, monkeypatch):
    from chinchilla.macos import pasteboard

    monkeypatch.setattr(pasteboard, "wait_for_image", lambda timeout: Image.new("RGB", (9, 9)))

    grab = capture.grab_area("clipboard")

    assert grab.backend == "clipboard"
    assert grab.image.size == (9, 9)


def test_mac_grab_screen_uses_screencapture(mac, tmp_path, monkeypatch):
    _fake_screencapture(tmp_path, monkeypatch)

    grab = capture.grab_screen()

    assert grab.backend == "screencapture"
    assert grab.image.size == (64, 32)


def test_mac_cancelled_area_selection_is_reported(mac, tmp_path, monkeypatch):
    _fake_screencapture(tmp_path, monkeypatch, cancel=True)

    with pytest.raises(capture.CaptureError, match="capture cancelled"):
        capture.grab_area()


def test_screencapture_is_not_offered_off_macos(monkeypatch):
    monkeypatch.setattr(system, "is_mac", lambda: False)

    assert "screencapture" not in [backend.id for backend in capture.backends()]


def test_crop_maps_points_to_retina_pixels():
    frame = Image.new("RGB", (2880, 1800), (255, 255, 255))
    frame.paste((0, 0, 0), (200, 100, 400, 300))

    cut = capture.crop(frame, capture.Rect(100, 50, 100, 100), (1440, 900))

    assert cut.size == (200, 200)
    assert cut.getpixel((5, 5)) == (0, 0, 0)


# ------------------------------------------------------------------- runtime


def test_mac_never_forces_the_x11_backend(mac, monkeypatch):
    from chinchilla.runtime import ensure_gdk_backend

    monkeypatch.delenv("GDK_BACKEND", raising=False)
    monkeypatch.delenv("CHINCHILLA_GDK_BACKEND", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")  # left behind by XQuartz

    ensure_gdk_backend()

    assert "GDK_BACKEND" not in os.environ


def test_mac_finds_an_installed_browser(mac, tmp_path, monkeypatch):
    from chinchilla.store import config

    browser = tmp_path / "Brave Browser"
    browser.write_text("", encoding="utf-8")
    monkeypatch.setattr(config, "MAC_BROWSERS", ("/nowhere/Chrome", str(browser)))

    assert config.default_chrome() == str(browser)


# ------------------------------------------------------------ single instance


def test_forward_without_a_running_instance(tmp_path):
    from chinchilla import instance

    assert instance.forward("capture", tmp_path / "missing.sock") is False


def test_listener_receives_commands_from_a_second_launch():
    pytest.importorskip("gi")
    from gi.repository import GLib

    from chinchilla import instance

    # AF_UNIX paths are limited to ~104 bytes on macOS, pytest's tmp_path is not
    folder = Path(tempfile.mkdtemp(prefix="chin", dir="/tmp"))
    path = folder / "control.sock"
    received: list[str] = []
    listener = instance.Listener(received.append, path)
    try:
        assert listener.start() is True
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        # a second launch must not steal the socket of a live one
        second = instance.Listener(received.append, path)
        assert second.start() is False
        assert second.taken is True
        assert path.exists()

        import threading

        results: list[bool] = []
        sender = threading.Thread(target=lambda: results.append(instance.forward("capture", path)))
        sender.start()
        context = GLib.MainContext.default()
        for _ in range(200):
            context.iteration(False)
            if results:
                break
            sender.join(0.01)
        sender.join(2)
        for _ in range(20):
            context.iteration(False)

        assert results == [True]
        assert "capture" in received
    finally:
        listener.stop()
    assert not path.exists()
    # the lock is released with the listener, so the next launch can take over
    third = instance.Listener(received.append, path)
    assert third.start() is True
    third.stop()
    for leftover in folder.iterdir():
        leftover.unlink()
    folder.rmdir()


def test_a_stale_socket_file_is_replaced(tmp_path):
    pytest.importorskip("gi")
    from chinchilla import instance

    folder = Path(tempfile.mkdtemp(prefix="chin", dir="/tmp"))
    path = folder / "control.sock"
    path.write_text("left over by a crash", encoding="utf-8")
    listener = instance.Listener(lambda _command: None, path)
    try:
        assert listener.start() is True
        assert stat.S_ISSOCK(path.stat().st_mode)
    finally:
        listener.stop()
        for leftover in folder.iterdir():
            leftover.unlink()
        folder.rmdir()


def test_cli_without_the_grant_only_waits_for_the_clipboard(mac, xdg, tmp_path, monkeypatch, capsys):
    from chinchilla.cli import main

    monkeypatch.delenv("CHINCHILLA_CAPTURE_SOURCE", raising=False)
    monkeypatch.setattr(permission, "ensure", lambda: (False, "not granted"))

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("no other backend may run without Screen Recording")

    monkeypatch.setattr(capture, "grab_screen", must_not_run)
    monkeypatch.setattr(capture, "grab_area", must_not_run)
    monkeypatch.setattr(capture, "grab_clipboard", lambda: Image.new("RGB", (40, 30)))

    assert main(["capture", "--out", str(tmp_path / "cut.jpg")]) == 0
    assert Image.open(tmp_path / "cut.jpg").size == (40, 30)
    assert "\u2318\u2303\u21e74" in capsys.readouterr().err


# ------------------------------------------------------------------- daemon


def test_daemon_restarts_a_stopped_agent_instead_of_duplicating_it(mac, monkeypatch, capsys):
    from chinchilla.cli import main

    started: list[bool] = []
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    monkeypatch.setattr(launchagent, "state", lambda: launchagent.AgentState(True, True, False))
    monkeypatch.setattr(launchagent, "kickstart", lambda restart=False: started.append(restart))

    assert main(["daemon"]) == 0
    assert started == [False]
    assert "started the login agent" in capsys.readouterr().out


def test_the_agent_itself_runs_the_app(mac, monkeypatch):
    from chinchilla.cli import main
    from chinchilla.ui import app as app_module

    ran: list[bool] = []
    monkeypatch.setenv("XPC_SERVICE_NAME", launchagent.LABEL)
    monkeypatch.setattr(launchagent, "state", lambda: launchagent.AgentState(True, True, False))
    monkeypatch.setattr(app_module, "run_app", lambda argv, capture=True: ran.append(capture) or 0)

    assert main(["daemon"]) == 0
    assert ran == [False]
