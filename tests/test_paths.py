from chinchilla import paths


def test_xdg_paths_follow_environment(xdg):
    paths.ensure_dirs()
    assert paths.settings_path() == xdg / "config" / "chinchilla" / "settings.json"
    assert paths.sessions_dir() == xdg / "data" / "chinchilla" / "sessions"
    assert paths.log_path() == xdg / "state" / "chinchilla" / "chinchilla.log"
    assert paths.sessions_dir().is_dir()


def test_cli_version(capsys):
    from chinchilla import cli

    assert cli.main(["version"]) == 0
    assert "chinchilla" in capsys.readouterr().out
