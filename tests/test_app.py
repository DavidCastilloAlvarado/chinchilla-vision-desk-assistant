import os
import time

import pytest
from PIL import Image

from chinchilla.core import llm
from chinchilla.core.agent import Agent
from chinchilla.store import config, session as session_store

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="needs a display to build GTK objects",
)


_apps = []


@pytest.fixture(autouse=True)
def _cleanup_apps():
    yield
    while _apps:
        app = _apps.pop()
        app.shutdown()


class StubProvider:
    def __init__(self, chunks=("Hello ", "from the stub.")):
        self.chunks = chunks
        self.seen: list[list[llm.Message]] = []

    def chat(self, messages, tools=None, stream=True):
        self.seen.append(list(messages))
        for text in self.chunks:
            yield llm.Chunk("text", text=text)


def _app(provider=None):
    from chinchilla.ui.app import App


    provider = provider or StubProvider()
    settings = config.default_settings()

    def factory(session, settings_):
        return Agent(session, settings_, provider=provider, search_factory=lambda: None)

    app = App(settings=settings, capture_on_activate=False, agent_factory=factory)
    app.build_ui()
    _apps.append(app)
    return app, provider


def _seed_capture(app) -> None:
    image = Image.new("RGB", (60, 40), (200, 30, 30))
    app.session.add_capture(image)
    app.window.content.set_captures(app.session.captures)


def _drain(app, timeout=10.0) -> None:
    from chinchilla.ui.gtk import Gtk

    deadline = time.monotonic() + timeout
    while app.busy and time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    assert app.busy is False, "the turn never finished"


def test_startup_builds_a_panel_and_a_session(xdg):
    app, _provider = _app()

    assert app.window is not None
    assert app.session.title
    assert app.window.content.provider_label.get_text()


def test_quick_action_streams_the_answer_into_the_panel(xdg):
    app, provider = _app()
    _seed_capture(app)

    app._on_action("translate", "translate")
    _drain(app)

    assert "Translate" in provider.seen[0][-1].text
    user_turns = [turn for turn in app.session.turns if turn.role == "user"]
    assert user_turns[-1].action == "translate"
    assistant = app.session.turns[-1]
    assert assistant.role == "assistant"
    assert assistant.text == "Hello from the stub."


def test_answers_are_persisted_to_the_session_file(xdg):
    app, _provider = _app()
    _seed_capture(app)

    app.submit("what is this?")
    _drain(app)

    stored = session_store.Session.load(app.session.id)
    assert stored is not None
    assert stored.turns[-1].text == "Hello from the stub."
    assert stored.captures[0].path


def test_prompt_without_a_capture_is_refused(xdg):
    app, provider = _app()

    app.submit("hello there")

    assert app.busy is False
    assert provider.seen == []
    assert "capture" in app.window.content.status_label.get_text()


def test_web_toggle_is_saved_with_the_session(xdg):
    app, _provider = _app()

    app.set_web(True)

    assert app.session.web_enabled is True
    assert session_store.Session.load(app.session.id).web_enabled is True


def test_new_session_resets_the_panel(xdg):
    app, _provider = _app()
    _seed_capture(app)
    app.submit("first")
    _drain(app)
    previous = app.session.id

    app.new_session()

    assert app.session.id != previous
    assert app.session.turns == []
    assert app.window.content.title_label.get_text() == app.session.title


def test_open_session_loads_the_stored_conversation(xdg):
    app, _provider = _app()
    _seed_capture(app)
    app.submit("remember me")
    _drain(app)
    stored = app.session.id
    app.new_session()

    app.open_session(stored)

    assert app.session.id == stored
    assert any(turn.text == "remember me" for turn in app.session.turns)


def test_add_capture_appends_to_the_open_session(xdg):
    app, _provider = _app()

    app.add_capture(Image.new("RGB", (20, 10), (10, 10, 10)))

    assert len(app.session.captures) == 1
    assert app.window.content is not None


def test_status_messages_reach_the_panel(xdg):
    app, _provider = _app()

    app._status("ready to test", "error")

    assert app.window.content.status_label.get_text() == "ready to test"


def test_settings_are_applied_to_the_panel(xdg):
    app, _provider = _app()
    settings = config.default_settings()
    settings.language = "German"

    app._apply_settings(settings)

    assert app.settings.language == "German"
    assert app.agent is None


def test_panel_close_hides_instead_of_quitting(xdg):
    app, _provider = _app()
    app.show_panel()
    assert app.window.get_visible() is True

    app.hide_panel()

    assert app.window.get_visible() is False


def test_session_widgets_are_kept_between_turns(xdg):
    app, _provider = _app()
    _seed_capture(app)
    app.submit("hi")
    _drain(app)

    assert app.window.content.title_label.get_text() == app.session.title