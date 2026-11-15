"""GitHub Copilot as a provider: device login, token exchange and models.

The Copilot subscription is not an API key: the official clients sign in with
the GitHub OAuth device flow, trade that token for a short lived Copilot token
and then talk to an OpenAI-compatible endpoint. That is the flow implemented
here, with no extra dependency (the published `github-copilot-sdk` drives the
Copilot CLI runtime over JSON-RPC, a process and a downloaded runtime per
session, which does not fit a provider that streams into this panel).

Nothing secret is ever logged: the tokens live in
``~/.config/chinchilla/copilot.json`` with mode 0600.
"""

from __future__ import annotations

import json
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from .. import log, paths
from ..store.config import DEFAULT_MAX_TOKENS
from .llm import OpenAICompatible, ProviderError

LOGGER = log.get("copilot")

# the OAuth app the Copilot editor plugins use; it only asks for read:user
CLIENT_ID = "Iv1.b507a08c87ecfe98"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
USER_URL = "https://api.github.com/user"
API_FALLBACK = "https://api.githubcopilot.com"
SCOPES = "read:user"
# the Copilot API wants to know which client is calling; these are the values
# the VS Code chat extension sends
INTEGRATION_ID = "vscode-chat"
EDITOR_VERSION = "vscode/1.99.0"
PLUGIN_VERSION = "copilot-chat/0.26.0"
USER_AGENT = "GitHubCopilotChat/0.26.0"
TOKEN_SAFETY_SECONDS = 120
TIMEOUT = 30.0


class CopilotError(ProviderError):
    """Login or Copilot API failure, with a message worth showing the user."""


@dataclass
class DeviceCode:
    """What the user needs to type at github.com/login/device."""

    device_code: str
    user_code: str
    verification_uri: str
    interval: float = 5.0
    expires_in: float = 900.0


@dataclass
class CopilotSession:
    """Short lived Copilot token plus the API host it belongs to."""

    token: str
    api: str = API_FALLBACK
    expires_at: float = 0.0

    @property
    def expires_in(self) -> float:
        return self.expires_at - time.time()

    def to_dict(self) -> dict:
        return {"token": self.token, "api": self.api, "expires_at": self.expires_at}


@dataclass
class CopilotModel:
    id: str
    name: str = ""
    efforts: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return self.name or self.id


# the chat completions endpoint is the one Chinchilla talks; several Copilot
# models (every GPT-5 and later, grok) are only served on /responses, so they
# would answer every turn with a 400
CHAT_ENDPOINT = "/chat/completions"


def _endpoints(row: dict) -> list[str]:
    endpoints = row.get("supported_endpoints")
    if not isinstance(endpoints, list):
        return []
    return [str(item) for item in endpoints if isinstance(item, str)]


def _model_efforts(row: dict) -> tuple[str, ...]:
    capabilities = row.get("capabilities")
    if not isinstance(capabilities, dict):
        return ()
    supports = capabilities.get("supports")
    if not isinstance(supports, dict):
        return ()
    efforts = supports.get("reasoning_effort")
    if not isinstance(efforts, list):
        return ()
    return tuple(str(item).strip().lower() for item in efforts if isinstance(item, str))


def _client(client: httpx.Client | None) -> httpx.Client | None:
    return client


def _post_form(url: str, data: dict, client: httpx.Client | None = None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    try:
        if client is not None:
            response = client.post(url, data=data, headers=headers)
        else:
            response = httpx.post(url, data=data, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise CopilotError(f"cannot reach GitHub: {exc}") from exc
    return _json(response)


def _get(url: str, headers: dict, client: httpx.Client | None = None) -> dict:
    try:
        if client is not None:
            response = client.get(url, headers=headers)
        else:
            response = httpx.get(url, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise CopilotError(f"cannot reach GitHub: {exc}") from exc
    return _json(response)


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and response.status_code < 400:
        return payload
    detail = ""
    if isinstance(payload, dict):
        detail = str(payload.get("error_description") or payload.get("message") or payload.get("error") or "")
    if not detail:
        detail = (response.text or "").strip()[:200]
    raise CopilotError(f"GitHub answered {response.status_code}: {detail or 'no detail'}")


# ----------------------------------------------------------------- device flow


def start_device_flow(client: httpx.Client | None = None) -> DeviceCode:
    """Ask GitHub for a code the user types in the browser."""
    payload = _post_form(
        DEVICE_CODE_URL,
        {"client_id": CLIENT_ID, "scope": SCOPES},
        client=client,
    )
    if not payload.get("device_code") or not payload.get("user_code"):
        raise CopilotError("GitHub did not return a device code")
    return DeviceCode(
        device_code=str(payload["device_code"]),
        user_code=str(payload["user_code"]),
        verification_uri=str(payload.get("verification_uri") or "https://github.com/login/device"),
        interval=float(payload.get("interval") or 5),
        expires_in=float(payload.get("expires_in") or 900),
    )


def _login_error(payload: dict) -> str:
    error = str(payload.get("error") or "")
    return {
        "expired_token": "the code expired, start the login again",
        "access_denied": "the login was cancelled on GitHub",
        "device_flow_disabled": "this GitHub app cannot use the device flow",
        "incorrect_client_credentials": "GitHub refused the client id",
        "unsupported_grant_type": "GitHub refused the device grant",
    }.get(error, f"GitHub said {error or 'nothing'}")


def wait_for_token(
    device: DeviceCode,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_pending: Callable[[], None] | None = None,
    max_wait: float | None = None,
) -> str:
    """Poll until the user finishes the login, then return the GitHub token."""
    deadline = time.monotonic() + (max_wait if max_wait is not None else device.expires_in)
    interval = device.interval
    while time.monotonic() < deadline:
        sleep(interval)
        payload = _post_form(
            ACCESS_TOKEN_URL,
            {
                "client_id": CLIENT_ID,
                "device_code": device.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            client=client,
        )
        token = payload.get("access_token")
        if token:
            return str(token)
        error = str(payload.get("error") or "")
        if error == "slow_down":
            interval += 5
            continue
        if error in ("", "authorization_pending"):
            if on_pending is not None:
                on_pending()
            continue
        raise CopilotError(_login_error(payload))
    raise CopilotError("the code expired, start the login again")


# ------------------------------------------------------------- copilot tokens


def copilot_session(github_token: str, client: httpx.Client | None = None) -> CopilotSession:
    """Trade the GitHub token for the Copilot token the API wants."""
    if not github_token:
        raise CopilotError("not signed in to GitHub Copilot")
    headers = {
        "Accept": "application/json",
        "Authorization": f"token {github_token}",
        "User-Agent": USER_AGENT,
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": PLUGIN_VERSION,
    }
    try:
        payload = _get(COPILOT_TOKEN_URL, headers, client=client)
    except CopilotError as exc:
        message = str(exc)
        if "401" in message or "403" in message or "404" in message:
            raise CopilotError(
                "this GitHub account has no Copilot subscription (or the token expired)"
            ) from exc
        raise
    token = str(payload.get("token") or "")
    if not token:
        raise CopilotError("GitHub returned no Copilot token")
    endpoints = payload.get("endpoints") or {}
    api = str(endpoints.get("api") or API_FALLBACK).rstrip("/")
    return CopilotSession(
        token=token,
        api=api,
        expires_at=float(payload.get("expires_at") or 0),
    )


def whoami(github_token: str, client: httpx.Client | None = None) -> str:
    """The GitHub login, for the "signed in as" line."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {github_token}",
        "User-Agent": USER_AGENT,
    }
    payload = _get(USER_URL, headers, client=client)
    return str(payload.get("login") or "")


def list_models(session: CopilotSession, client: httpx.Client | None = None) -> list[CopilotModel]:
    """Chat models this subscription can pick."""
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {session.token}",
        "User-Agent": USER_AGENT,
        "Copilot-Integration-Id": INTEGRATION_ID,
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": PLUGIN_VERSION,
        "X-GitHub-Api-Version": "2025-04-01",
    }
    payload = _get(f"{session.api}/models", headers, client=client)
    rows = payload.get("data") if isinstance(payload.get("data"), list) else payload
    models: dict[str, CopilotModel] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        capabilities = row.get("capabilities") or {}
        if isinstance(capabilities, dict) and capabilities.get("type") not in (None, "", "chat"):
            continue
        if row.get("model_picker_enabled") is False:
            continue
        endpoints = _endpoints(row)
        if endpoints and CHAT_ENDPOINT not in endpoints:
            continue
        models[model_id] = CopilotModel(
            id=model_id,
            name=str(row.get("name") or ""),
            efforts=_model_efforts(row),
        )
    return sorted(models.values(), key=lambda model: (model.label.lower(), model.id))


# ---------------------------------------------------------------- credentials


@dataclass
class Credentials:
    """Everything the app needs to talk to Copilot without asking again."""

    github_token: str = ""
    token: str = ""
    api: str = API_FALLBACK
    expires_at: float = 0.0
    login: str = ""

    @classmethod
    def path(cls) -> Path:
        return paths.config_dir() / "copilot.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "Credentials":
        target = path or cls.path()
        if not target.is_file():
            return cls()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(
            github_token=str(data.get("github_token") or ""),
            token=str(data.get("token") or ""),
            api=str(data.get("api") or API_FALLBACK),
            expires_at=float(data.get("expires_at") or 0),
            login=str(data.get("login") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "github_token": self.github_token,
            "token": self.token,
            "api": self.api,
            "expires_at": self.expires_at,
            "login": self.login,
        }

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temporary.replace(target)
        return target

    def clear(self, path: Path | None = None) -> None:
        target = path or self.path()
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        self.github_token = ""
        self.token = ""
        self.expires_at = 0.0
        self.login = ""

    @property
    def signed_in(self) -> bool:
        return bool(self.github_token)

    def session(self, client: httpx.Client | None = None, force: bool = False) -> CopilotSession:
        """The cached Copilot token, refreshed when it is about to expire."""
        if not self.github_token:
            raise CopilotError("not signed in to GitHub Copilot")
        if not force and self.token and self.expires_at - TOKEN_SAFETY_SECONDS > time.time():
            return CopilotSession(token=self.token, api=self.api, expires_at=self.expires_at)
        fresh = copilot_session(self.github_token, client=client)
        self.token = fresh.token
        self.api = fresh.api
        self.expires_at = fresh.expires_at
        try:
            self.save()
        except OSError as exc:  # a read only config dir should not break a turn
            LOGGER.warning("cannot save the copilot token: %s", exc)
        return fresh

    def describe(self) -> str:
        if not self.signed_in:
            return "not signed in"
        who = f"signed in as {self.login}" if self.login else "signed in"
        return who


def login(
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_code: Callable[[DeviceCode], None] | None = None,
    on_pending: Callable[[], None] | None = None,
) -> Credentials:
    """Whole flow: show the code, wait for the browser, validate the seat."""
    device = start_device_flow(client=client)
    if on_code is not None:
        on_code(device)
    github_token = wait_for_token(device, client=client, sleep=sleep, on_pending=on_pending)
    credentials = Credentials(github_token=github_token)
    try:
        credentials.login = whoami(github_token, client=client)
    except CopilotError as exc:  # cosmetic, never fail the login for it
        LOGGER.warning("cannot read the GitHub login: %s", exc)
    session = credentials.session(client=client, force=True)
    credentials.token = session.token
    credentials.api = session.api
    credentials.expires_at = session.expires_at
    credentials.save()
    return credentials

class CopilotProvider(OpenAICompatible):
    """The Copilot chat endpoint, authenticated with the stored credentials."""

    def __init__(
        self,
        model: str,
        credentials: Credentials | None = None,
        client: httpx.Client | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str = "",
        provider_id: str = "copilot",
    ) -> None:
        if not model:
            raise ProviderError("copilot: choose a model in Settings › Providers first")
        self.credentials = credentials if credentials is not None else Credentials.load()
        session = self.credentials.session(client=client)
        super().__init__(
            provider_id,
            session.api,
            session.token,
            model,
            client=client,
            max_tokens=max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
            reasoning_effort=reasoning_effort,
        )
        self.base_url = session.api.rstrip("/")

    def _headers(self) -> dict[str, str]:
        # a long turn can outlive the token, so it is refreshed per request
        session = self.credentials.session(client=self._client)
        self.base_url = session.api.rstrip("/")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {session.token}",
            "Copilot-Integration-Id": INTEGRATION_ID,
            "Editor-Version": EDITOR_VERSION,
            "Editor-Plugin-Version": PLUGIN_VERSION,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2025-04-01",
        }

    def _narrow_optional(self, field: str, exc: ProviderError) -> bool:
        """Copilot lists the efforts a model takes; pick the closest one."""
        if field != "reasoning_effort" or self._drop_reasoning:
            return False
        narrowed = _closest_effort(self.reasoning_effort, str(exc))
        if not narrowed or narrowed == self.reasoning_effort:
            return False
        self.reasoning_effort = narrowed
        return True


# the effort levels Copilot understands, weakest first
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")
_SUPPORTED_EFFORTS = re.compile(r"supported values?:?\s*\[([^\]]*)\]")


def _closest_effort(effort: str, message: str) -> str:
    """The strongest effort the model accepts that is not above the request.

    Copilot answers a refusal with "supported values: [low medium high]", so a
    gemini model asked for `xhigh` can still think at `high` instead of losing
    the reasoning altogether.
    """
    match = _SUPPORTED_EFFORTS.search(message.lower())
    if match is None or effort not in EFFORT_ORDER:
        return ""
    offered = [item for item in re.split(r"[\s,]+", match.group(1).strip()) if item in EFFORT_ORDER]
    if not offered:
        return ""
    wanted = EFFORT_ORDER.index(effort)
    below = [item for item in offered if EFFORT_ORDER.index(item) <= wanted]
    if below:
        return max(below, key=EFFORT_ORDER.index)
    return min(offered, key=EFFORT_ORDER.index)
