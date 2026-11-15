import json

from PIL import Image

from chinchilla import paths
from chinchilla.core.thread import Turn
from chinchilla.store import config, session as session_store


def test_settings_round_trip(xdg):
    settings = config.default_settings()
    settings.active_provider = "openai"
    settings.language = "German"
    settings.actions[0].title = "Traducir"
    path = config.save_settings(settings)
    loaded = config.load_settings(path)
    assert loaded.active_provider == "openai"
    assert loaded.language == "German"
    assert loaded.action("translate").title == "Traducir"
    assert loaded.action("explain").title == "Explain"


def test_settings_fall_back_when_corrupt(xdg):
    path = paths.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    settings = config.load_settings()
    assert settings.active_provider == "custom"
    assert len(settings.actions) == 3


def test_custom_provider_reads_dotenv(xdg, tmp_path, monkeypatch):
    env = xdg / "config" / "chinchilla" / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("LLM_BASE_URL=https://example.test/v1\nLLM_MODEL=test-model\n", encoding="utf-8")
    monkeypatch.setattr(config, "env_files", lambda: [env])
    provider = config.provider_from_env("custom")
    assert provider.base_url == "https://example.test/v1"
    assert provider.model == "test-model"


def test_key_lookup_prefers_environment(xdg, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert config.resolve_key("openai") == "sk-test"
    assert config.key_source("openai") == "env:OPENAI_API_KEY"


def test_key_can_be_saved_to_the_credentials_file(xdg):
    config.save_credential("anthropic", "sk-secret")
    assert config.resolve_key("anthropic") == "sk-secret"
    assert config.key_source("anthropic") == "file"
    path = paths.credentials_path()
    assert path.stat().st_mode & 0o777 == 0o600


def test_session_round_trip(xdg):
    paths_ok = session_store.paths.ensure_dirs()
    del paths_ok
    session = session_store.Session(title="Round trip")
    session.add_turn(Turn(role="user", text="hello"))
    session.add_turn(Turn(role="assistant", text="hi", sources=[]))
    saved = session.save()
    assert saved.exists()

    loaded = session_store.Session.load(session.id)
    assert loaded is not None
    assert loaded.title == "Round trip"
    assert [turn.text for turn in loaded.turns] == ["hello", "hi"]


def test_capture_is_written_next_to_the_session(xdg):
    session = session_store.Session()
    capture = session.add_capture(Image.new("RGB", (200, 100), (10, 20, 30)))
    from pathlib import Path

    assert Path(capture.path).exists()
    assert capture.width == 200 and capture.height == 100
    assert session.last_capture().id == capture.id


def test_captures_are_pending_until_a_turn_sends_them(xdg):
    session = session_store.Session()
    capture = session.add_capture(Image.new("RGB", (20, 20)))
    assert [item.id for item in session.pending_captures()] == [capture.id]

    session.mark_sent([capture.id])
    session.save()

    assert session.pending_captures() == []
    reloaded = session_store.Session.load(session.id)
    assert reloaded is not None
    assert reloaded.capture(capture.id).sent is True
    assert reloaded.pending_captures() == []


def test_autotitle_uses_the_first_prompt(xdg):
    session = session_store.Session()
    session.autotitle("Translate this dashboard error message please")
    assert session.title.startswith("Translate this dashboard")
    session.rename("  my   title ")
    assert session.title == "my title"


def test_listing_is_newest_first(xdg):
    session_store.paths.ensure_dirs()
    first = session_store.Session(title="first")
    first.updated_at = 1000
    first.save()
    second = session_store.Session(title="second")
    second.updated_at = 2000
    second.save()
    titles = [item.title for item in session_store.list_sessions()]
    assert titles == ["second", "first"]


def test_prune_removes_old_sessions(xdg):
    session_store.paths.ensure_dirs()
    old = session_store.Session(title="old")
    old.updated_at = 1000
    old.save()
    fresh = session_store.Session(title="fresh")
    fresh.save()
    removed = session_store.prune(days=7)
    assert removed == 1
    assert [item.title for item in session_store.list_sessions()] == ["fresh"]


def test_corrupt_session_file_is_ignored(xdg):
    session_store.paths.ensure_dirs()
    (session_store.paths.sessions_dir() / "broken.json").write_text("[]", encoding="utf-8")
    assert session_store.list_sessions() == []


def test_session_json_is_readable(xdg):
    session = session_store.Session()
    session.add_turn(Turn(role="user", text="hi"))
    session.save()
    data = json.loads(session.path.read_text(encoding="utf-8"))
    assert data["turns"][0]["role"] == "user"


def test_exported_endpoint_wins_over_the_saved_settings(xdg, monkeypatch):
    settings = config.default_settings()
    settings.active_provider = "custom"
    settings.providers["custom"].base_url = "http://saved:1234/v1"
    settings.providers["custom"].model = "saved-model"
    monkeypatch.setenv("LLM_BASE_URL", "http://exported:8000/v1")
    monkeypatch.setenv("LLM_MODEL", "exported-model")

    resolved = config.resolved_provider(settings)

    assert resolved.base_url == "http://exported:8000/v1"
    assert resolved.model == "exported-model"
    assert config.provider_origin(settings) == {
        "base_url": "environment (LLM_BASE_URL)",
        "model": "environment (LLM_MODEL)",
    }


def test_a_dotenv_value_also_wins_over_the_saved_settings(xdg, monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        config,
        "load_env",
        lambda: {"LLM_BASE_URL": "http://from-dotenv:1/v1", "LLM_MODEL": "dotenv-model"},
    )
    settings = config.default_settings()
    settings.active_provider = "custom"
    settings.providers["custom"].base_url = "http://saved:1234/v1"

    resolved = config.resolved_provider(settings)

    assert resolved.base_url == "http://from-dotenv:1/v1"
    assert config.provider_origin(settings)["base_url"] == ".env (LLM_BASE_URL)"


def test_origin_falls_back_to_the_settings_file(xdg, monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_env", lambda: {})
    settings = config.default_settings()
    settings.active_provider = "custom"
    settings.providers["custom"].base_url = "http://saved:1234/v1"

    assert config.provider_origin(settings) == {
        "base_url": "settings file",
        "model": "settings file",
    }


def test_a_value_saved_in_the_dialog_wins_over_the_dotenv(xdg, monkeypatch):
    monkeypatch.setattr(
        config,
        "load_env",
        lambda: {"LLM_BASE_URL": "http://from-dotenv:1/v1", "LLM_MODEL": "dotenv-model"},
    )
    settings = config.default_settings()
    settings.active_provider = "custom"
    settings.providers["custom"].base_url = "http://typed-here:1234/v2"
    settings.custom_explicit = ["base_url"]

    resolved = config.resolved_provider(settings)

    assert resolved.base_url == "http://typed-here:1234/v2"
    assert resolved.model == "dotenv-model"
    assert config.provider_origin(settings) == {
        "base_url": "settings file (saved in the dialog)",
        "model": ".env (LLM_MODEL)",
    }


def test_custom_explicit_round_trips_through_the_settings_file():
    settings = config.default_settings()
    settings.custom_explicit = ["base_url"]

    loaded = config.Settings.from_dict(settings.to_dict())

    assert loaded.custom_explicit == ["base_url"]


def test_unknown_explicit_fields_are_dropped():
    settings = config.Settings.from_dict({"custom_explicit": ["base_url", "nonsense"]})

    assert settings.custom_explicit == ["base_url"]


def test_effective_provider_resolves_a_provider_that_is_not_active(xdg, monkeypatch):
    settings = config.default_settings()
    settings.active_provider = "openai"
    settings.providers["custom"].base_url = "http://settings:1/v1"
    monkeypatch.setenv("LLM_BASE_URL", "http://exported:1/v1")

    assert config.effective_provider(settings, "custom").base_url == "http://exported:1/v1"
    assert config.effective_provider(settings, "openai").id == "openai"


def test_reasoning_effort_defaults_to_medium_and_round_trips():
    settings = config.default_settings()
    assert settings.reasoning_effort == "medium"

    settings.reasoning_effort = "xhigh"
    assert config.Settings.from_dict(settings.to_dict()).reasoning_effort == "xhigh"


def test_reasoning_effort_ignores_unknown_values():
    assert config.Settings.from_dict({"reasoning_effort": "turbo"}).reasoning_effort == "medium"
    assert config.Settings.from_dict({"reasoning_effort": " HIGH "}).reasoning_effort == "high"


def test_the_output_budget_defaults_to_32k_and_round_trips():
    settings = config.default_settings()
    assert settings.max_tokens == 32768

    settings.max_tokens = 8192
    assert config.Settings.from_dict(settings.to_dict()).max_tokens == 8192


def test_a_nonsense_budget_falls_back_to_the_default():
    assert config.Settings.from_dict({"max_tokens": 0}).max_tokens == 32768
    assert config.Settings.from_dict({"max_tokens": "lots"}).max_tokens == 32768
