"""XDG locations used by Chinchilla."""

from __future__ import annotations

import os
from pathlib import Path

APP = "chinchilla"


def _base(env_var: str, fallback: str) -> Path:
    root = os.environ.get(env_var) or os.path.expanduser(fallback)
    return Path(root) / APP


def config_dir() -> Path:
    return _base("XDG_CONFIG_HOME", "~/.config")


def data_dir() -> Path:
    return _base("XDG_DATA_HOME", "~/.local/share")


def state_dir() -> Path:
    return _base("XDG_STATE_HOME", "~/.local/state")


def settings_path() -> Path:
    return config_dir() / "settings.json"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def sessions_dir() -> Path:
    return data_dir() / "sessions"


def captures_dir() -> Path:
    return data_dir() / "captures"


def log_path() -> Path:
    return state_dir() / "chinchilla.log"


def socket_path() -> Path:
    return state_dir() / "control.sock"


def ensure_dirs() -> None:
    for path in (config_dir(), data_dir(), state_dir(), sessions_dir(), captures_dir()):
        path.mkdir(parents=True, exist_ok=True)
