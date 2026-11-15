import argparse
import json
import stat

import httpx
import pytest

from chinchilla.core import copilot, llm


def route(routes: dict[str, object]):
    """A mock transport that answers by URL path, and records what it saw."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        for path, answer in routes.items():
            if request.url.path == path:
                status, payload = answer if isinstance(answer, tuple) else (200, answer)
                return httpx.Response(status, json=payload)
        return httpx.Response(404, json={"message": "no route"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return client, seen


DEVICE = {
    "device_code": "dev-code",
    "user_code": "ABCD-1234",
    "verification_uri": "https://github.com/login/device",
    "expires_in": 900,
    "interval": 5,
}
COPILOT_TOKEN = {
    "token": "tid=abc;exp=999",
    "expires_at": 4102444800,
    "endpoints": {"api": "https://api.githubcopilot.com"},
}


def test_the_device_flow_returns_the_code_to_type():
    client, seen = route({"/login/device/code": DEVICE})

    device = copilot.start_device_flow(client=client)

    assert device.user_code == "ABCD-1234"
    assert device.verification_uri == "https://github.com/login/device"
    assert device.interval == 5
    assert seen[0].method == "POST"
    assert b"client_id=" + copilot.CLIENT_ID.encode() in seen[0].content


def test_pending_polls_until_the_user_approves():
    answers = [
        {"error": "authorization_pending"},
        {"error": "slow_down"},
        {"access_token": "gho_token"},
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=answers.pop(0))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    devices = copilot.DeviceCode("dev", "ABCD", "https://github.com/login/device", interval=0.01)
    token = copilot.wait_for_token(devices, client=client, sleep=lambda _s: None)

    assert token == "gho_token"
    assert answers == []


def test_a_cancelled_login_says_so():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "access_denied"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    device = copilot.DeviceCode("dev", "ABCD", "https://github.com/login/device", interval=0.01)

    with pytest.raises(copilot.CopilotError) as error:
        copilot.wait_for_token(device, client=client, sleep=lambda _s: None)

    assert "cancelled" in str(error.value)


def test_an_expired_code_says_so():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "expired_token"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    device = copilot.DeviceCode("dev", "ABCD", "https://github.com/login/device", interval=0.01)

    with pytest.raises(copilot.CopilotError) as error:
        copilot.wait_for_token(device, client=client, sleep=lambda _s: None)

    assert "expired" in str(error.value)


def test_the_github_token_is_traded_for_a_copilot_token():
    client, seen = route({"/copilot_internal/v2/token": COPILOT_TOKEN})

    session = copilot.copilot_session("gho_x", client=client)

    assert session.token == "tid=abc;exp=999"
    assert session.api == "https://api.githubcopilot.com"
    assert seen[0].headers["authorization"] == "token gho_x"
    assert "Editor-Version" in seen[0].headers


def test_an_account_without_a_seat_gets_a_clear_message():
    client, _seen = route({"/copilot_internal/v2/token": (403, {"message": "forbidden"})})

    with pytest.raises(copilot.CopilotError) as error:
        copilot.copilot_session("gho_x", client=client)

    assert "no Copilot subscription" in str(error.value)


def test_only_chat_models_are_offered():
    client, seen = route(
        {
            "/models": {
                "data": [
                    {"id": "gpt-4o", "name": "GPT-4o", "capabilities": {"type": "chat"}},
                    {"id": "text-embedding", "capabilities": {"type": "embeddings"}},
                    {"id": "hidden", "model_picker_enabled": False},
                    {"id": "claude-sonnet-4", "name": "Claude Sonnet 4"},
                    {"name": "no id"},
                ]
            }
        }
    )
    session = copilot.CopilotSession(token="tid=abc")

    models = copilot.list_models(session, client=client)

    assert [model.id for model in models] == ["claude-sonnet-4", "gpt-4o"]
    assert models[0].label == "Claude Sonnet 4"
    assert seen[0].headers["authorization"] == "Bearer tid=abc"
    assert seen[0].headers["Copilot-Integration-Id"] == copilot.INTEGRATION_ID


def test_models_served_only_by_the_responses_api_are_hidden():
    client, _seen = route(
        {
            "/models": {
                "data": [
                    {
                        "id": "gpt-5.6-sol",
                        "name": "GPT 5.6 Sol",
                        "capabilities": {
                            "type": "chat",
                            "supports": {"reasoning_effort": ["low", "high", "xhigh"]},
                        },
                        "supported_endpoints": ["/responses", "ws:/responses"],
                    },
                    {
                        "id": "claude-sonnet-5",
                        "name": "Claude Sonnet 5",
                        "capabilities": {
                            "type": "chat",
                            "supports": {"reasoning_effort": ["low", "medium", "high"]},
                        },
                        "supported_endpoints": ["/v1/messages", "/chat/completions"],
                    },
                    {"id": "legacy", "name": "Legacy"},
                ]
            }
        }
    )

    models = copilot.list_models(copilot.CopilotSession(token="tid=abc"), client=client)

    assert [model.id for model in models] == ["claude-sonnet-5", "legacy"]
    assert models[0].efforts == ("low", "medium", "high")


def test_the_effort_is_lowered_to_what_the_model_offers():
    message = (
        'copilot: HTTP 400 reasoning_effort "xhigh" is not supported by model '
        "gemini-3.8-flash; supported values: [low medium high]"
    )
    offered = "[low medium high]"

    assert copilot._closest_effort("xhigh", message) == "high"
    assert copilot._closest_effort("medium", message) == "medium"
    assert copilot._closest_effort("low", f"supported values: {offered}") == "low"
    assert copilot._closest_effort("xhigh", "supported values: [high xhigh]") == "xhigh"
    assert copilot._closest_effort("", message) == ""
    assert copilot._closest_effort("high", "no list here") == ""
    assert copilot._closest_effort("high", "supported values: [none]") == ""


def test_a_refused_effort_is_narrowed_instead_of_dropped():
    credentials = copilot.Credentials(github_token="gho_x", token="t", expires_at=9_999_999_999)
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        if payload.get("reasoning_effort") == "xhigh":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": 'reasoning_effort "xhigh" is not supported by model '
                        "gemini-3.8-flash; supported values: [low medium high]"
                    }
                },
            )
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')

    provider = copilot.CopilotProvider(
        "gemini-3.8-flash",
        credentials=credentials,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        reasoning_effort="xhigh",
    )

    text = "".join(chunk.text for chunk in provider.chat([llm.Message(role="user", text="hi")]) if chunk.type == "text")

    assert text == "ok"
    assert provider.reasoning_effort == "high"
    assert provider._drop_reasoning is False
    assert [payload.get("reasoning_effort") for payload in payloads] == ["xhigh", "high"]


def test_the_status_command_reports_the_saved_model(xdg, tmp_path, monkeypatch, capsys):
    from chinchilla import cli
    from chinchilla.store import config

    path = tmp_path / "copilot.json"
    copilot.Credentials(github_token="gho_x", token="t", expires_at=9_999_999_999, login="david").save(path)
    monkeypatch.setattr(copilot.Credentials, "path", classmethod(lambda cls: path))
    monkeypatch.setattr(
        copilot, "list_models", lambda session, client=None: [copilot.CopilotModel("claude-sonnet-5")]
    )
    settings = config.default_settings()
    settings.providers["copilot"].model = "claude-sonnet-5"
    config.save_settings(settings)

    code = cli.cmd_copilot(argparse.Namespace(action="status", model=None))

    out = capsys.readouterr().out
    assert code == 0
    assert "signed in as david" in out
    assert "models: 1" in out
    assert "model: claude-sonnet-5" in out


def test_the_status_command_says_how_to_sign_in(xdg, capsys):
    from chinchilla import cli

    code = cli.cmd_copilot(argparse.Namespace(action="status", model=None))

    out = capsys.readouterr().out
    assert code == 1
    assert "not signed in" in out
    assert "chinchilla copilot login" in out


def test_credentials_are_saved_private_and_readable(tmp_path):
    path = tmp_path / "copilot.json"
    credentials = copilot.Credentials(github_token="gho_x", token="t", expires_at=1, login="david")

    credentials.save(path)
    loaded = copilot.Credentials.load(path)

    assert loaded.github_token == "gho_x"
    assert loaded.login == "david"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_signing_out_removes_the_file(tmp_path):
    path = tmp_path / "copilot.json"
    credentials = copilot.Credentials(github_token="gho_x")
    credentials.save(path)

    credentials.clear(path)

    assert not path.exists()
    assert credentials.signed_in is False


def test_a_valid_token_is_reused_and_a_stale_one_refreshed(tmp_path, monkeypatch):
    path = tmp_path / "copilot.json"
    credentials = copilot.Credentials(github_token="gho_x", token="old", expires_at=9_999_999_999)
    monkeypatch.setattr(copilot.Credentials, "path", classmethod(lambda cls: path))

    assert credentials.session().token == "old"

    calls = []

    def fake_session(token, client=None):
        calls.append(token)
        return copilot.CopilotSession(token="new", expires_at=1_000_000)

    credentials.expires_at = 0
    monkeypatch.setattr(copilot, "copilot_session", fake_session)

    assert credentials.session().token == "new"
    assert calls == ["gho_x"]
    assert copilot.Credentials.load(path).token == "new"


def test_signed_out_credentials_cannot_start_a_session():
    with pytest.raises(copilot.CopilotError) as error:
        copilot.Credentials().session()

    assert "not signed in" in str(error.value)


def test_the_provider_sends_the_copilot_headers(monkeypatch):
    credentials = copilot.Credentials(github_token="gho_x", token="tid=abc", expires_at=9_999_999_999)
    monkeypatch.setattr(copilot, "copilot_session", lambda *a, **k: pytest.fail("no refresh expected"))

    provider = copilot.CopilotProvider(model="gpt-4o", credentials=credentials, client=None)
    headers = provider._headers()

    assert provider.base_url == "https://api.githubcopilot.com"
    assert headers["Authorization"] == "Bearer tid=abc"
    assert headers["Copilot-Integration-Id"] == copilot.INTEGRATION_ID
    assert headers["Editor-Version"]
    assert headers["Copilot-Integration-Id"] == "vscode-chat"


def test_a_copilot_request_without_a_model_asks_for_one():
    credentials = copilot.Credentials(github_token="gho_x", token="t", expires_at=9_999_999_999)

    with pytest.raises(llm.ProviderError) as error:
        copilot.CopilotProvider(model="", credentials=credentials)

    assert "choose a model" in str(error.value)


def test_the_provider_loads_the_credentials_from_disk(xdg, tmp_path, monkeypatch):
    path = tmp_path / "copilot.json"
    copilot.Credentials(github_token="gho_x", token="tid=abc", expires_at=9_999_999_999).save(path)
    monkeypatch.setattr(copilot.Credentials, "path", classmethod(lambda cls: path))

    provider = copilot.CopilotProvider(model="gpt-4o")

    assert provider._headers()["Authorization"] == "Bearer tid=abc"


def test_a_copilot_401_names_the_subscription():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(copilot.CopilotError) as error:
        copilot.copilot_session("gho_bad", client=client)

    assert "no Copilot subscription" in str(error.value)


def test_the_settings_round_trip_keeps_the_copilot_model(xdg):
    from chinchilla.store import config

    settings = config.default_settings()
    assert "copilot" in settings.providers
    settings.providers["copilot"].model = "claude-sonnet-4"

    loaded = config.Settings.from_dict(settings.to_dict())

    assert loaded.providers["copilot"].model == "claude-sonnet-4"


def test_the_copilot_kind_builds_the_copilot_provider(xdg, tmp_path, monkeypatch):
    from chinchilla.store import config

    path = tmp_path / "copilot.json"
    copilot.Credentials(github_token="gho_x", token="tid=abc", expires_at=9_999_999_999).save(path)
    monkeypatch.setattr(copilot.Credentials, "path", classmethod(lambda cls: path))

    settings = config.default_settings()
    settings.active_provider = "copilot"
    settings.providers["copilot"].model = "claude-sonnet-5"

    provider = llm.build_provider(settings)

    assert isinstance(provider, copilot.CopilotProvider)
    assert provider.model == settings.providers["copilot"].model