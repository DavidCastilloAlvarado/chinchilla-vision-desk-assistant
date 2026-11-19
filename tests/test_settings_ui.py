import os
import sys

import pytest

from chinchilla.store import config

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or sys.platform == "darwin"  # Quartz always has a display
    ),
    reason="needs a display to build GTK objects",
)


@pytest.fixture(autouse=True)
def _isolated_config(xdg):
    """Never read the real ~/.config/chinchilla, the Copilot block looks there."""
    return xdg


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

def _dotenv(monkeypatch, base_url="http://from-dotenv:1/v1", model="dotenv-model"):
    monkeypatch.setattr(
        config, "load_env", lambda: {"LLM_BASE_URL": base_url, "LLM_MODEL": model}
    )


def test_custom_fields_show_the_dotenv_value(xdg, monkeypatch):
    _dotenv(monkeypatch)
    content = _content()
    widgets = content.provider_widgets["custom"]

    assert widgets["base_url"].get_text() == "http://from-dotenv:1/v1"
    assert widgets["model"].get_text() == "dotenv-model"
    assert widgets["base_url"].get_sensitive()
    notes = content.origin_notes["custom"]
    assert "LLM_BASE_URL" in notes["base_url"].get_text()


def test_typing_a_different_endpoint_overrides_the_dotenv(xdg, monkeypatch):
    _dotenv(monkeypatch)
    content = _content()
    content.provider_widgets["custom"]["base_url"].set_text("http://typed:1234/v2")

    collected = content.collect()

    assert collected.custom_explicit == ["base_url"]
    assert config.resolved_provider(collected).base_url == "http://typed:1234/v2"
    assert config.resolved_provider(collected).model == "dotenv-model"


def test_keeping_the_dotenv_value_keeps_the_environment_as_source(xdg, monkeypatch):
    _dotenv(monkeypatch)
    content = _content()

    collected = content.collect()

    assert collected.custom_explicit == []
    assert config.resolved_provider(collected).base_url == "http://from-dotenv:1/v1"


def test_save_status_is_empty_until_the_user_saves(xdg, monkeypatch):
    _dotenv(monkeypatch)
    content = _content()

    assert content.save_statuses[0].get_text() == ""

    content.save()

    assert content.save_statuses[0].get_text() == "saved to settings.json"


def test_toggle_switch_slides_its_knob_with_the_state():
    from chinchilla.ui.gtk import Gtk
    from chinchilla.ui.settings import ToggleSwitch

    switch = ToggleSwitch(active=False)
    assert switch._track.query_child_packing(switch._knob).pack_type == Gtk.PackType.START

    switch.set_active(True)

    assert switch._track.query_child_packing(switch._knob).pack_type == Gtk.PackType.END
    assert switch._knob.get_parent() is switch._track

    switch.set_active(False)

    assert switch._track.query_child_packing(switch._knob).pack_type == Gtk.PackType.START


def test_settings_toggles_start_in_the_state_they_were_built_with():
    from chinchilla.ui.settings import ToggleSwitch

    switch = ToggleSwitch(active=True)

    assert switch.get_active() is True
    assert switch._track.get_style_context().has_class("on")


def test_the_general_page_sets_the_reasoning_effort():
    settings = config.default_settings()
    content = _content(settings)
    assert content.effort_combo.get_active_id() == "medium"

    content.effort_combo.set_active_id("low")

    assert content.collect().reasoning_effort == "low"


def test_the_general_page_sets_the_output_budget():
    content = _content()
    assert content.tokens_spin.get_value() == 32768

    content.tokens_spin.set_value(8192)

    assert content.collect().max_tokens == 8192


def test_the_copilot_block_starts_signed_out():
    content = _content()

    assert content.provider_widgets["copilot"]["model"] is content.copilot_combo
    assert content.copilot_combo.get_active_id() is None
    assert content.copilot_status.get_text() == "not signed in"
    assert content.copilot_sign_out.get_sensitive() is False


def test_the_model_list_fills_the_combo_and_keeps_the_saved_choice():
    from chinchilla.core import copilot

    settings = config.default_settings()
    settings.providers["copilot"].model = "claude-sonnet-4"
    content = _content(settings)

    content._copilot_models_loaded(
        [
            copilot.CopilotModel(id="gpt-4o", name="GPT-4o"),
            copilot.CopilotModel(id="claude-sonnet-4", name="Claude Sonnet 4"),
        ]
    )

    assert content.copilot_combo.get_active_id() == "claude-sonnet-4"
    assert "2 models" in content.copilot_status.get_text()


def test_an_unknown_saved_model_falls_back_to_the_first_one():
    from chinchilla.core import copilot

    settings = config.default_settings()
    settings.providers["copilot"].model = "retired-model"
    content = _content(settings)

    content._copilot_models_loaded([copilot.CopilotModel(id="gpt-4o", name="GPT-4o")])

    assert content.copilot_combo.get_active_id() == "gpt-4o"


def test_collect_activates_copilot_with_the_chosen_model():
    from chinchilla.core import copilot

    content = _content()
    content.provider_widgets["copilot"]["radio"].set_active(True)
    content._copilot_models_loaded([copilot.CopilotModel(id="gpt-4o", name="GPT-4o")])

    collected = content.collect()

    assert collected.active_provider == "copilot"
    assert collected.providers["copilot"].model == "gpt-4o"


def test_signing_out_clears_the_model_list(monkeypatch, tmp_path):
    from chinchilla.core import copilot

    path = tmp_path / "copilot.json"
    copilot.Credentials(github_token="gho_x", token="tid", expires_at=9_999_999_999, login="david").save(path)
    monkeypatch.setattr(copilot.Credentials, "path", classmethod(lambda cls: path))
    monkeypatch.setattr(copilot, "list_models", lambda session, client=None: [])

    content = _content()
    content._copilot_models_loaded([copilot.CopilotModel(id="gpt-4o")])
    content._on_copilot_sign_out()

    assert content.copilot_combo.get_active_id() is None
    assert content.copilot_status.get_text() == "not signed in"
    assert not path.exists()


def test_the_login_dialog_starts_the_flow_and_closes_itself():
    from chinchilla.core import copilot
    from chinchilla.ui.copilot_login import CopilotLoginDialog

    shown = []

    def fake_login(on_code=None, **_kwargs):
        device = copilot.DeviceCode(
            device_code="dev",
            user_code="ABCD-1234",
            verification_uri="https://github.com/login/device",
        )
        if on_code is not None:
            on_code(device)
        shown.append("code")
        return copilot.Credentials(github_token="gho_x", token="t", expires_at=1, login="david")

    dialog = CopilotLoginDialog(login=fake_login)
    dialog.run()

    assert shown == ["code"]
    assert dialog.credentials is not None
    assert dialog.credentials.login == "david"
    assert dialog.code_label.get_text() == "ABCD-1234"
    dialog.destroy()


def test_the_open_button_goes_to_the_device_page(monkeypatch):
    from chinchilla.core import copilot
    from chinchilla.ui import copilot_login
    from chinchilla.ui.copilot_login import CopilotLoginDialog

    opened = []
    monkeypatch.setattr(copilot_login.Gtk, "show_uri_on_window", lambda window, uri, stamp: opened.append(uri))

    dialog = CopilotLoginDialog(login=lambda **_kwargs: copilot.Credentials())
    dialog._open_page()
    dialog._show_code(
        copilot.DeviceCode(device_code="dev", user_code="ABCD-1234", verification_uri="https://github.com/login/device?x=1")
    )
    dialog._open_page()
    dialog.destroy()

    assert opened == ["https://github.com/login/device", "https://github.com/login/device?x=1"]
