"""Settings, provider definitions and API key lookup."""

from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    "copilot": {
        "label": "GitHub Copilot",
        "base_url": "https://api.githubcopilot.com",
        "model": "",
        "key_env": "",
        "kind": "copilot",
    },
    "custom": {
        "label": "Custom",
        "base_url": "",
        "model": "",
        "key_env": "LLM_API_KEY",
        "kind": "openai",
    },
}

CUSTOM_FIELDS = {"base_url": "LLM_BASE_URL", "model": "LLM_MODEL"}

MCP_PACKAGE = "dsh-google-chrome-search"
DEFAULT_CHROME = "/usr/bin/google-chrome"
DEFAULT_PROFILE_DIR = "~/.dsh-chrome-google"
# ------------------------------------------------------------ web search tools


def find_node_bin(name: str) -> str | None:
    """`npx` is often installed outside PATH (nvm, ~/.local/node, ...)."""
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    folders = [home / ".local/node/bin", home / ".volta/bin", home / ".bun/bin"]
    for pattern in (".nvm/versions/node/*/bin", ".fnm/node-versions/*/installation/bin"):
        folders.extend(sorted(home.glob(pattern), reverse=True))
    for folder in folders:
        candidate = folder / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def default_mcp_command() -> list[str]:
    """Same server the other desktop project uses, launched with a real npx."""
    npx = find_node_bin("npx") or "npx"
    return [npx, "-y", MCP_PACKAGE, "mcp"]


def default_mcp_env() -> dict[str, str]:
    chrome = DEFAULT_CHROME
    if not Path(chrome).is_file():
        found = shutil.which("google-chrome") or shutil.which("chromium") or ""
        chrome = found or DEFAULT_CHROME
    return {
        "CHROME_PATH": chrome,
        "GSEARCH_PROFILE": str(Path(os.path.expanduser(DEFAULT_PROFILE_DIR))),
    }


def env_value(name: str) -> str:
    """Real environment wins over the .env files."""
    return (os.environ.get(name) or load_env().get(name) or "").strip()


def resolved_mcp(settings: "Settings") -> tuple[list[str], dict[str, str]]:
    """Launch details for the MCP server, with the environment as override."""
    command = list(settings.mcp_command) or default_mcp_command()
    raw_command = env_value("WEBSEARCH_MCP_COMMAND")
    if raw_command:
        args = env_value("WEBSEARCH_MCP_ARGS") or f"-y {MCP_PACKAGE} mcp"
        command = [raw_command, *args.split()]
    resolved = find_node_bin(Path(command[0]).name)
    if resolved and not Path(command[0]).is_absolute():
        command[0] = resolved
    merged = default_mcp_env()
    merged.update({key: str(value) for key, value in settings.mcp_env.items() if value})
    for key in ("CHROME_PATH", "GSEARCH_PROFILE"):
        override = env_value(key)
        if override:
            merged[key] = override
    node_dir = str(Path(command[0]).parent)
    if node_dir and node_dir not in os.environ.get("PATH", "").split(os.pathsep):
        merged["PATH"] = os.pathsep.join(
            [node_dir, merged.get("PATH", os.environ.get("PATH", ""))]
        ).strip(os.pathsep)
    return command, merged


DEFAULT_LANGUAGE = "Spanish"
DEFAULT_LEVEL = "B1"
DEFAULT_MAX_SIDE = 1400
# generations are not cut on purpose: a thinking model needs room for both the
# reasoning and the answer, and a server that refuses the value gets a retry
DEFAULT_MAX_TOKENS = 32768
REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
DEFAULT_REASONING = "medium"


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
    max_tokens: int = DEFAULT_MAX_TOKENS
    reasoning_effort: str = DEFAULT_REASONING
    panel_width: int = 404
    hotkey: str = "<Control><Alt>a"
    mcp_command: list[str] = field(default_factory=default_mcp_command)
    mcp_enabled: bool = True
    mcp_env: dict[str, str] = field(default_factory=default_mcp_env)
    # custom-provider fields the user saved in the dialog, which then win over
    # LLM_BASE_URL / LLM_MODEL. Empty means the environment decides.
    custom_explicit: list[str] = field(default_factory=list)

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
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "panel_width": self.panel_width,
            "hotkey": self.hotkey,
            "mcp_command": list(self.mcp_command),
            "mcp_enabled": self.mcp_enabled,
            "mcp_env": dict(self.mcp_env),
            "custom_explicit": list(self.custom_explicit),
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

        effort = data.get("reasoning_effort")
        if isinstance(effort, str) and effort.strip().lower() in REASONING_EFFORTS:
            settings.reasoning_effort = effort.strip().lower()
        for key in ("language", "level", "hotkey"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                setattr(settings, key, value.strip())
        for key in ("web_enabled", "save_sessions", "mcp_enabled"):
            if key in data:
                setattr(settings, key, bool(data[key]))
        for key in ("retention_days", "max_side", "max_tokens", "panel_width"):
            if isinstance(data.get(key), (int, float)) and data[key] > 0:
                setattr(settings, key, int(data[key]))
        if isinstance(data.get("mcp_command"), list) and data["mcp_command"]:
            settings.mcp_command = [str(part) for part in data["mcp_command"]]
        if isinstance(data.get("mcp_env"), dict):
            settings.mcp_env = {str(key): str(value) for key, value in data["mcp_env"].items()}
        explicit = data.get("custom_explicit") or []
        settings.custom_explicit = [str(name) for name in explicit if name in CUSTOM_FIELDS]
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


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def is_local_endpoint(url: str) -> bool:
    """True for a model server on this machine, which accepts requests without a key."""
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and (host in LOCAL_HOSTS or host.startswith("127."))


def env_source(name: str) -> str:
    """Where a variable comes from: 'environment', '.env' or '' when unset."""
    if os.environ.get(name):
        return "environment"
    if load_env().get(name):
        return ".env"
    return ""


def provider_origin(settings: "Settings") -> dict[str, str]:
    """Explain the effective endpoint and model, for `doctor --verbose`."""
    provider = settings.active()
    if provider.id != "custom":
        return {"base_url": "built in", "model": "settings file"}
    origin = {"base_url": "settings file", "model": "settings file"}
    explicit = set(settings.custom_explicit)
    for field, name in CUSTOM_FIELDS.items():
        if field in explicit and getattr(provider, field):
            origin[field] = "settings file (saved in the dialog)"
        elif env_value(name):
            origin[field] = f"{env_source(name)} ({name})"
    return origin


def provider_from_env(provider_id: str = "custom") -> ProviderSettings:
    """Custom provider details come from LLM_BASE_URL / LLM_MODEL.

    The real environment wins over the .env files, like every other setting, so
    `export LLM_BASE_URL=http://localhost:8000/v1` works for a local server.
    """
    provider = default_provider(provider_id)
    if provider_id == "custom":
        provider.base_url = env_value("LLM_BASE_URL") or provider.base_url
        provider.model = env_value("LLM_MODEL") or provider.model
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
    """Active provider, resolving who wins for a custom endpoint.

    `LLM_BASE_URL` / `LLM_MODEL` (environment or .env) are the default source,
    so editing `.env` moves to another server without touching the GUI. A value
    typed into the settings dialog and saved is recorded in
    `Settings.custom_explicit` and wins for that field until it is cleared or
    reset to the environment value there.
    """
    return effective_provider(settings, settings.active_provider)


def effective_provider(settings: Settings, provider_id: str) -> ProviderSettings:
    """Resolve one provider, whether or not it is the active one."""
    provider = settings.providers.get(provider_id) or default_provider(provider_id)
    if provider.id != "custom":
        return provider
    explicit = set(settings.custom_explicit)
    base_url = provider.base_url
    model = provider.model
    if "base_url" not in explicit or not base_url:
        base_url = env_value("LLM_BASE_URL") or base_url
    if "model" not in explicit or not model:
        model = env_value("LLM_MODEL") or model
    return ProviderSettings(
        id=provider.id,
        base_url=base_url,
        model=model,
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
