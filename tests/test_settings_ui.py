import os

import pytest

from chinchilla.store import config

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="needs a display to build GTK objects",
)


def _content(settings=None):
    from chinchilla.ui.settings import SettingsContent

    return SettingsContent(settings or config.default_settings())


def test_collect_round_trips_the_settings():
    original = config.default_settings()
    collected = _content(original).collect()

    assert collected.language == original.language
    assert collected.level == original.level
    assert collected.hotkey == original.hotkey
    assert [action.id for action in collected.actions] == [
        action.id for action in original.actions
    ]
    assert [action.prompt for action in collected.actions] == [
        action.prompt for action in original.actions
    ]


def test_collect_reads_edited_action_titles_and_prompts():
    content = _content()
    content.language_entry.set_text("German")
    title_entry, prompt_view, _switch = content.action_rows["translate"]
    title_entry.set_text("Traducir")
    prompt_view.get_buffer().set_text("Translate into {language}.")

    collected = content.collect()
    action = collected.action("translate")

    assert collected.language == "German"
    assert action.title == "Traducir"
    assert action.prompt == "Translate into {language}."


def test_collect_reads_the_active_provider_and_its_endpoint():
    content = _content()
    widgets = content.provider_widgets["openai"]
    widgets["radio"].set_active(True)
    widgets["base_url"].set_text("https://proxy.local/v1")
    widgets["model"].set_text("gpt-4o")

    collected = content.collect()

    assert collected.active_provider == "openai"
    assert collected.active().base_url == "https://proxy.local/v1"
    assert collected.active().model == "gpt-4o"


def test_save_writes_the_settings_file(xdg):
    from chinchilla.store import session  # noqa: F401  keeps import order stable

    content = _content()
    content.level_entry.set_text("C1")
    content.save()

    assert config.load_settings().level == "C1"


def test_collect_reads_the_web_search_section():
    content = _content()
    content.mcp_switch.set_active(False)
    content.mcp_command_entry.set_text("python3 -m fakemcp")
    content.chrome_entry.set_text("/usr/bin/google-chrome")
    content.profile_entry.set_text("Profile 2")

    collected = content.collect()

    assert collected.mcp_enabled is False
    assert collected.mcp_command == ["python3", "-m", "fakemcp"]
    assert collected.mcp_env["CHROME_PATH"] == "/usr/bin/google-chrome"
    assert collected.mcp_env["GSEARCH_PROFILE"] == "Profile 2"


def test_settings_render_writes_a_png(xdg, tmp_path):
    from chinchilla.cli import main

    target = tmp_path / "settings.png"
    assert main(["settings", "--render", str(target), "--page", "1"]) == 0
    assert target.is_file() and target.stat().st_size > 4000