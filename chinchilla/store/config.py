"""Settings, provider definitions and API key lookup."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths
from ..core.prompts import DEFAULT_ACTIONS

PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "kind": "openai",
    },
    "anthropic": {
        "label": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
        "key_env": "ANTHROPIC_API_KEY",
        "kind": "anthropic",
    },
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "key_env": "OPENROUTER_API_KEY",
        "kind": "openai",
    },
    "custom": {
        "label": "Custom",
        "base_url": "",
        "model": "",
        "key_env": "LLM_API_KEY",
        "kind": "openai",
    },
}

DEFAULT_LANGUAGE = "Spanish"
DEFAULT_LEVEL = "B1"
DEFAULT_MAX_SIDE = 1400


@dataclass
class ProviderSettings:
    id: str
    base_url: str
    model: str
    enabled: bool = True

    @property
    def label(self) -> str:
        return PROVIDERS.get(self.id, {}).get("label", self.id)

    @property
    def kind(self) -> str:
        return PROVIDERS.get(self.id, {}).get("kind", "openai")

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "enabled": self.enabled,
        }


@dataclass
class ActionSettings:
    id: str
    title: str
    prompt: str
    web_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "prompt": self.prompt,
            "web_default": self.web_default,
        }


@dataclass
class Settings:
    active_provider: str = "custom"
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    actions: list[ActionSettings] = field(default_factory=list)
    language: str = DEFAULT_LANGUAGE
    level: str = DEFAULT_LEVEL
    web_enabled: bool = False
    save_sessions: bool = True
    retention_days: int = 0
    max_side: int = DEFAULT_MAX_SIDE
    panel_width: int = 404
    hotkey: str = "<Control><Alt>a"
    mcp_command: list[str] = field(default_factory=lambda: ["npx", "-y", "dsh-google-chrome-search", "mcp"])
    mcp_enabled: bool = True
    mcp_env: dict[str, str] = field(default_factory=dict)

    # -------------------------------------------------------------- providers

    def active(self) -> ProviderSettings:
        provider = self.providers.get(self.active_provider)
        if provider is None:
            provider = default_provider(self.active_provider)
        return provider

    def provider_label(self) -> str:
        provider = resolved_provider(self)
        model = provider.model or "no model"
        return f"{provider.label.lower()} \u00b7 {model}"

    def action(self, action_id: str) -> ActionSettings | None:
        return next((action for action in self.actions if action.id == action_id), None)

    # ------------------------------------------------------------- (de)serial

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "active_provider": self.active_provider,
            "providers": {pid: provider.to_dict() for pid, provider in self.providers.items()},
            "actions": [action.to_dict() for action in self.actions],
            "language": self.language,
            "level": self.level,
            "web_enabled": self.web_enabled,
            "save_sessions": self.save_sessions,
            "retention_days": self.retention_days,
            "max_side": self.max_side,
            "panel_width": self.panel_width,
            "hotkey": self.hotkey,
            "mcp_command": list(self.mcp_command),
            "mcp_enabled": self.mcp_enabled,
            "mcp_env": dict(self.mcp_env),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        data = data or {}
        settings = cls()
        settings.active_provider = data.get("active_provider") or settings.active_provider
        settings.providers = default_providers()
        raw_providers = data.get("providers") or {}
        for provider_id, values in raw_providers.items():
            provider = settings.providers.get(provider_id) or default_provider(provider_id)
            if isinstance(values, dict):
                provider.base_url = values.get("base_url", provider.base_url)
                provider.model = values.get("model", provider.model)
                provider.enabled = bool(values.get("enabled", provider.enabled))
            settings.providers[provider_id] = provider

        settings.actions = default_actions()
        for values in data.get("actions") or []:
            if not isinstance(values, dict) or not values.get("id"):
                continue
            action_id = values["id"]
            existing = settings.action(action_id)
            if existing is None:
                existing = ActionSettings(
                    id=action_id,
                    title=values.get("title") or action_id.title(),
                    prompt=values.get("prompt") or "",
                )
                settings.actions.append(existing)
            existing.title = values.get("title", existing.title)
            existing.prompt = values.get("prompt", existing.prompt)
            existing.web_default = bool(values.get("web_default", existing.web_default))

        for key in ("language", "level", "hotkey"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                setattr(settings, key, value.strip())
        for key in ("web_enabled", "save_sessions", "mcp_enabled"):
            if key in data:
                setattr(settings, key, bool(data[key]))
        for key in ("retention_days", "max_side", "panel_width"):
            if isinstance(data.get(key), (int, float)) and data[key] > 0:
                setattr(settings, key, int(data[key]))
        if isinstance(data.get("mcp_command"), list) and data["mcp_command"]:
            settings.mcp_command = [str(part) for part in data["mcp_command"]]
        if isinstance(data.get("mcp_env"), dict):
            settings.mcp_env = {str(key): str(value) for key, value in data["mcp_env"].items()}
        return settings


def default_provider(provider_id: str) -> ProviderSettings:
    base = PROVIDERS.get(provider_id, PROVIDERS["custom"])
    return ProviderSettings(
        id=provider_id,
        base_url=base["base_url"],
        model=base["model"],
    )


def default_providers() -> dict[str, ProviderSettings]:
    return {provider_id: default_provider(provider_id) for provider_id in PROVIDERS}


def default_actions() -> list[ActionSettings]:
    return [
        ActionSettings(
            id=action["id"],
            title=action["title"],
            prompt=action["prompt"],
            web_default=bool(action.get("web_default")),
        )
        for action in DEFAULT_ACTIONS
    ]


def default_settings() -> Settings:
    return Settings(providers=default_providers(), actions=default_actions())


# -------------------------------------------------------------------- storage


def load_settings(path: Path | None = None) -> Settings:
    target = path or paths.settings_path()
    if not target.is_file():
        return default_settings()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_settings()
    return Settings.from_dict(data)


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    target = path or paths.settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


# ----------------------------------------------------------------- .env / keys


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def env_files() -> list[Path]:
    candidates = [paths.config_dir() / ".env"]
    root = Path(__file__).resolve().parents[2]
    candidates.append(root / ".env")
    return candidates


def load_env() -> dict[str, str]:
    """Values from the project .env files, without touching os.environ."""
    merged: dict[str, str] = {}
    for path in env_files():
        merged.update(parse_env_file(path))
    return merged


def provider_from_env(provider_id: str = "custom") -> ProviderSettings:
    """Custom provider details come from LLM_BASE_URL / LLM_MODEL."""
    env = load_env()
    provider = default_provider(provider_id)
    if provider_id == "custom":
        provider.base_url = env.get("LLM_BASE_URL", provider.base_url)
        provider.model = env.get("LLM_MODEL", provider.model)
    return provider


def credential_store() -> dict[str, str]:
    path = paths.credentials_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(key): str(value) for key, value in data.items() if value}


def save_credential(provider_id: str, key: str) -> Path:
    path = paths.credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = credential_store()
    if key:
        data[provider_id] = key
    else:
        data.pop(provider_id, None)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def resolve_key(provider_id: str) -> str | None:
    """Environment wins over the credentials file."""
    base = PROVIDERS.get(provider_id, PROVIDERS["custom"])
    env_names = [base["key_env"]]
    if provider_id == "custom":
        env_names += ["OPENAI_API_KEY"]
    for name in env_names:
        value = os.environ.get(name)
        if value:
            return value
        env_value = load_env().get(name)
        if env_value:
            return env_value
    return credential_store().get(provider_id)


def resolved_provider(settings: Settings) -> ProviderSettings:
    """Active provider with the environment filling the custom endpoint."""
    provider = settings.active()
    if provider.id != "custom":
        return provider
    env = provider_from_env("custom")
    return ProviderSettings(
        id=provider.id,
        base_url=provider.base_url or env.base_url,
        model=provider.model or env.model,
        enabled=provider.enabled,
    )


def key_source(provider_id: str) -> str:
    base = PROVIDERS.get(provider_id, PROVIDERS["custom"])
    env_names = [base["key_env"]]
    if provider_id == "custom":
        env_names += ["OPENAI_API_KEY"]
    for name in env_names:
        if os.environ.get(name) or load_env().get(name):
            return f"env:{name}"
    if credential_store().get(provider_id):
        return "file"
    return "missing"
