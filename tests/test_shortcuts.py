import json
import os
import stat

import pytest

from chinchilla import shortcuts

FAKE = '''#!/usr/bin/env python3
import json
import os
import sys

store_path = os.environ["FAKE_GSETTINGS_STORE"]
try:
    with open(store_path) as handle:
        store = json.load(handle)
except (OSError, ValueError):
    store = {}

args = sys.argv[1:]
action = args[0] if args else ""
if action == "get":
    schema, key = args[1], args[2]
    print(store.get(schema + "|" + key, "@as []"))
elif action == "set":
    schema, key, value = args[1:4]
    store[schema + "|" + key] = value
    with open(store_path, "w") as handle:
        json.dump(store, handle)
elif action == "reset":
    schema, key = args[1], args[2]
    store.pop(schema + "|" + key, None)
    with open(store_path, "w") as handle:
        json.dump(store, handle)
else:
    sys.exit(2)
'''


@pytest.fixture()
def fake_gsettings(tmp_path, monkeypatch):
    binary = tmp_path / "bin" / "gsettings"
    binary.parent.mkdir(parents=True)
    binary.write_text(FAKE, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    store = tmp_path / "store.json"
    store.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{binary.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_GSETTINGS_STORE", str(store))
    return store


def test_parse_and_format_keybindings():
    raw = "['/org/gnome/a/', '/org/gnome/b/']"
    assert shortcuts.parse_keybindings(raw) == ["/org/gnome/a/", "/org/gnome/b/"]
    assert shortcuts.parse_keybindings("@as []") == []
    assert (
        shortcuts.format_keybindings(["/a/", "/b/"]) == "['/a/', '/b/']"
    )


def test_status_is_not_installed_without_the_slot(fake_gsettings):
    status = shortcuts.status()

    assert status.available is True
    assert status.installed is False
    assert status.summary == "not installed"


def test_install_registers_the_slot_and_keeps_other_bindings(fake_gsettings):
    other = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/other/"
    fake_gsettings.write_text(
        json.dumps({f"{shortcuts.MEDIA_KEYS}|custom-keybindings": f"['{other}']"}),
        encoding="utf-8",
    )

    status = shortcuts.install("chinchilla capture --panel", "<Control><Alt>a")

    assert status.installed is True
    assert status.binding == "<Control><Alt>a"
    data = json.loads(fake_gsettings.read_text(encoding="utf-8"))
    registered = data[f"{shortcuts.MEDIA_KEYS}|custom-keybindings"]
    assert other in registered
    assert shortcuts.BASE_PATH in registered
    schema = f"{shortcuts.CUSTOM_KEYBINDING}:{shortcuts.BASE_PATH}"
    assert data[f"{schema}|command"] == "chinchilla capture --panel"
    assert data[f"{schema}|name"] == shortcuts.DEFAULT_NAME


def test_status_reports_the_installed_binding(fake_gsettings):
    shortcuts.install("chinchilla capture --panel", "<Control><Shift>c")

    status = shortcuts.status()

    assert status.installed is True
    assert status.binding == "<Control><Shift>c"
    assert "chinchilla capture --panel" in status.summary


def test_uninstall_removes_only_our_slot(fake_gsettings):
    other = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/other/"
    fake_gsettings.write_text(
        json.dumps({f"{shortcuts.MEDIA_KEYS}|custom-keybindings": f"['{other}']"}),
        encoding="utf-8",
    )
    shortcuts.install()

    status = shortcuts.uninstall()

    assert status.installed is False
    data = json.loads(fake_gsettings.read_text(encoding="utf-8"))
    assert data[f"{shortcuts.MEDIA_KEYS}|custom-keybindings"] == f"['{other}']"
    assert shortcuts.status().installed is False


def test_missing_gsettings_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    status = shortcuts.status()

    assert status.available is False
    assert status.installed is False
    with pytest.raises(shortcuts.ShortcutError):
        shortcuts.install()


def test_cli_shortcuts_commands(fake_gsettings, capsys):
    from chinchilla.cli import main

    assert main(["shortcuts", "install"]) == 0
    assert "chinchilla capture --panel" in capsys.readouterr().out
    assert main(["shortcuts", "status"]) == 0
    assert main(["shortcuts", "uninstall"]) == 0
    assert main(["shortcuts", "status"]) == 1