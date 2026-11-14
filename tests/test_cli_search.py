import sys
from pathlib import Path

from chinchilla import cli
from chinchilla.store import config

FAKE = Path(__file__).with_name("fake_mcp_server.py")


def fake_settings():
    settings = config.default_settings()
    settings.mcp_command = [sys.executable, str(FAKE)]
    return settings


def test_search_command_prints_sources(monkeypatch, capsys):
    monkeypatch.setattr(config, "load_settings", fake_settings)

    code = cli.main(["search", "token expiry"])

    out = capsys.readouterr().out
    assert code == 0
    assert "https://example.com/tokens" in out
    assert "[1] Token expiry explained" in out


def test_search_command_fails_when_the_server_is_missing(monkeypatch, capsys):
    settings = config.default_settings()
    settings.mcp_command = ["definitely-not-a-real-binary", "mcp"]
    monkeypatch.setattr(config, "load_settings", lambda: settings)

    code = cli.main(["search", "x"])

    assert code == 1
    assert "not installed" in capsys.readouterr().err
