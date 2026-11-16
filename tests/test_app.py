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
        yield llm.Chunk(
            "usage",
            usage={
                "prompt_tokens": 1200,
                "completion_tokens": 40,
                "prompt_tokens_details": {"cached_tokens": 900},
            },
        )


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


def test_prompt_without_a_capture_is_a_plain_chat(xdg):
    app, provider = _app()

    app.submit("hello there")
    _drain(app)

    assert provider.seen, "the model should be asked even without a cut"
    user_turns = [turn for turn in app.session.turns if turn.role == "user"]
    assert user_turns[-1].captures == []
    assert app.session.turns[-1].text == "Hello from the stub."


def test_quick_action_without_a_capture_is_refused(xdg):
    app, provider = _app()

    app._on_action("translate", "translate")

    assert app.busy is False
    assert provider.seen == []
    assert "cut" in app.window.content.status_label.get_text()


def test_follow_up_after_a_capture_carries_no_image(xdg):
    app, provider = _app()
    _seed_capture(app)
    app.submit("what is this?")
    _drain(app)
    sent = len(provider.seen)

    app.submit("and what colour is it?")
    _drain(app)

    user_turns = [turn for turn in app.session.turns if turn.role == "user"]
    assert user_turns[0].captures and user_turns[-1].captures == []
    second_request = provider.seen[sent][-1]
    assert second_request.text == "and what colour is it?"
    assert second_request.images == []


def test_a_capture_is_attached_to_one_turn_only(xdg):
    app, provider = _app()
    _seed_capture(app)

    app.submit("first look")
    _drain(app)
    app.submit("second look")
    _drain(app)
    app.add_capture(Image.new("RGB", (30, 20), (0, 90, 200)))
    app.submit("new cut")
    _drain(app)

    user_turns = [turn for turn in app.session.turns if turn.role == "user"]
    assert [len(turn.captures) for turn in user_turns] == [1, 0, 1]
    assert user_turns[2].captures[0] == app.session.captures[-1].id


def test_usage_line_updates_after_a_turn(xdg):
    app, _provider = _app()
    assert app.window.content.usage_label.get_text() == ""

    app.submit("hello")
    _drain(app)

    assert app.window.content.usage_label.get_text() == "in 1.2k · out 40 · cache 75%"
    stored = session_store.Session.load(app.session.id)
    assert stored.turns[-1].usage.cached_tokens == 900


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


def test_refresh_config_reads_the_file_again(xdg):
    app, _provider = _app()
    changed = config.load_settings()
    changed.language = "Japanese"
    config.save_settings(changed)

    assert app.refresh_config() is True
    assert app.settings.language == "Japanese"
    assert app.refresh_config() is False, "a second read with no changes is a no-op"


def test_provider_label_follows_the_environment_without_a_restart(xdg, monkeypatch):
    app, _provider = _app()
    app.settings.active_provider = "custom"
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("LLM_MODEL", "exported-vl")
    monkeypatch.setenv("LLM_API_KEY", "local")

    app.refresh_config()

    label = app.window.content.provider_label
    assert "exported-vl" in label.get_text()
    assert label.get_tooltip_text().startswith("http://127.0.0.1:9999/v1")


def test_activation_reloads_the_config_before_capturing(xdg):
    app, _provider = _app()
    changed = config.load_settings()
    changed.language = "Klingon"
    config.save_settings(changed)

    app.do_activate()  # the daemon path consumes the first activation

    assert app.capture_on_activate is True
    assert app.settings.language == "Klingon"


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


def test_starting_a_capture_hides_the_panel(xdg, monkeypatch):
    from chinchilla.ui import app as app_module

    app, _provider = _app()
    app.show_panel()
    calls = []
    monkeypatch.setattr(
        app_module.GLib, "timeout_add", lambda delay, fn: calls.append((delay, fn)) or 0
    )

    app.start_capture()

    assert app.window.get_visible() is False
    assert app.status == ""
    assert calls and calls[0][0] == app_module.CAPTURE_DELAY_MS


def test_session_widgets_are_kept_between_turns(xdg):
    app, _provider = _app()
    _seed_capture(app)
    app.submit("hi")
    _drain(app)

    assert app.window.content.title_label.get_text() == app.session.title

def test_capture_falls_back_to_the_desktop_selector(xdg, monkeypatch):
    from chinchilla.core import capture as capture_module
    from chinchilla.ui import app as app_module

    app, _provider = _app()
    app.capture_parent = "x11:0x1"
    seen = {}

    def boom(parent=None):
        seen["parent"] = parent
        raise capture_module.CaptureError("portal refused")

    monkeypatch.setattr(capture_module, "grab_screen", boom)
    monkeypatch.setattr(
        capture_module,
        "grab_area",
        lambda: capture_module.Grab(image=Image.new("RGB", (30, 20)), backend="portal-area"),
    )
    monkeypatch.setattr(app_module.permission, "ensure", lambda: (True, "granted"))
    monkeypatch.setattr(app_module.GLib, "idle_add", lambda fn, *args: fn(*args))
    monkeypatch.setattr(
        app, "_run_area_selector", lambda reason="": seen.setdefault("fallback", True) or False
    )

    app._capture_worker()

    assert seen["parent"] == "x11:0x1"
    assert seen.get("fallback") is True

    app._area_worker()

    assert len(app.session.captures) == 1


def test_capture_skips_the_portal_without_the_screenshot_permission(xdg, monkeypatch):
    from chinchilla.ui import app as app_module

    app, _provider = _app()
    seen = {}
    monkeypatch.setattr(app_module.system, "is_mac", lambda: False)

    def should_not_run(**kwargs):
        raise AssertionError("the portal must not be called without permission")

    monkeypatch.setattr(app_module.capture_module, "grab_screen", should_not_run)
    monkeypatch.setattr(app_module.permission, "ensure", lambda: (False, "no permission store"))
    monkeypatch.setattr(app_module.GLib, "idle_add", lambda fn, *args: fn(*args))
    monkeypatch.setattr(
        app, "_run_area_selector", lambda reason="": seen.setdefault("reason", reason) or False
    )

    app._capture_worker()

    assert "no permission store" in seen["reason"]



def test_mac_without_screen_recording_takes_every_clipboard_cut(xdg, monkeypatch):
    """Every ⌘⌃⇧4 cut arrives while the panel is open, not only the first."""
    from chinchilla.macos import pasteboard
    from chinchilla.ui import app as app_module

    app, _provider = _app()
    board = {"count": 41, "image": None}
    timers: list = []

    def should_not_run(**kwargs):
        raise AssertionError("a blank frame must not be grabbed without Screen Recording")

    monkeypatch.setattr(app_module.system, "is_mac", lambda: True)
    monkeypatch.setattr(app_module.capture_module, "grab_screen", should_not_run)
    monkeypatch.setattr(app_module.permission, "ensure", lambda: (False, "not granted"))
    monkeypatch.setattr(app_module.permission, "is_granted", lambda: False)
    monkeypatch.setattr(app_module.GLib, "idle_add", lambda fn, *args: fn(*args))
    monkeypatch.setattr(app_module.GLib, "timeout_add", lambda _ms, fn: timers.append(fn) or 99)
    monkeypatch.setattr(pasteboard, "change_count", lambda: board["count"])
    monkeypatch.setattr(pasteboard, "read_image", lambda: board["image"])

    def copy(image=None):
        board["count"] += 1
        board["image"] = image

    app._capture_worker()  # the hotkey without the grant opens the panel and waits
    assert app.window.get_visible()
    assert "\u2318\u2303\u21e74" in app.status
    assert len(timers) == 1
    poll = timers[0]

    assert poll() is True  # nothing copied yet
    copy(Image.new("RGB", (80, 50)))
    assert poll() is True  # the first cut does not end the watch
    copy()  # a text copy is not a cut, and is skipped quietly
    assert poll() is True
    copy(Image.new("RGB", (300, 40)))
    assert poll() is True

    assert [(cut.width, cut.height) for cut in app.session.captures] == [(80, 50), (300, 40)]
    assert len(timers) == 1  # one watch, never restarted by add_capture
    assert "adds another" in app.status

    app.hide_panel()
    assert poll() is False  # a hidden panel stops watching
    assert app._clipboard_timer is None

    app.show_panel()  # shown again, from the menu or the hotkey
    assert len(timers) == 2
    app._clipboard_timer = None



def test_a_failing_clipboard_cut_keeps_the_watch_alive(xdg, monkeypatch):
    from chinchilla.macos import pasteboard
    from chinchilla.ui import app as app_module

    app, _provider = _app()
    board = {"count": 5}
    app.show_panel()
    monkeypatch.setattr(pasteboard, "change_count", lambda: board["count"])

    def explode():
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr(pasteboard, "read_image", explode)
    app._clipboard_since = 5
    board["count"] = 6

    assert app._poll_clipboard() is True  # still watching
    assert "cannot take that cut" in app.status

    monkeypatch.setattr(pasteboard, "read_image", lambda: Image.new("RGB", (20, 10)))
    board["count"] = 7
    assert app._poll_clipboard() is True
    assert [(cut.width, cut.height) for cut in app.session.captures] == [(20, 10)]

def test_mac_second_launch_hands_over_and_builds_nothing(xdg, monkeypatch):
    import tempfile
    from pathlib import Path

    from chinchilla import instance, paths
    from chinchilla.ui import app as app_module

    # AF_UNIX paths are limited to ~104 bytes on macOS, the xdg tmp path is not
    folder = Path(tempfile.mkdtemp(prefix="chin", dir="/tmp"))
    monkeypatch.setattr(paths, "socket_path", lambda: folder / "control.sock")
    monkeypatch.setattr(app_module.system, "is_mac", lambda: True)
    forwarded: list[str] = []
    monkeypatch.setattr(instance, "forward", lambda command, path=None: forwarded.append(command) or True)

    first, _provider = _app()
    second, _provider = _app()

    assert first.listener is not None and first.window is not None
    assert second._duplicate is True
    assert second.window is None and second.tray is None and second.hotkey is None
    assert forwarded == ["daemon"]

    first.shutdown()
    for leftover in folder.iterdir():
        leftover.unlink()
    folder.rmdir()

def test_picking_a_row_in_the_session_selector_opens_that_session(xdg):
    app, _provider = _app()
    _seed_capture(app)
    app.submit("first thread")
    _drain(app)
    stored = app.session.id
    app.new_session()
    current = app.session.id

    app.toggle_sessions()
    pane = app.sessions_popover.pane
    rows = pane.listbox.get_children()
    target = next(
        row
        for row in rows
        if getattr(row, "session_id", None) == stored
    )
    target.get_child().clicked()

    assert app.session.id == stored
    assert app.session.id != current
    assert app.window.content.title_label.get_text() == app.session.title


class SlowProvider:
    """Yields one chunk at a time, waiting for the test to let it continue."""

    def __init__(self):
        import threading

        self.chunks = ["first ", "second ", "third"]
        self.release = threading.Event()
        self.seen = 0

    def chat(self, messages, tools=None, stream=True):
        self.seen += 1
        for text in self.chunks:
            self.release.wait(5)
            yield llm.Chunk("text", text=text)


def test_stop_keeps_the_text_that_already_arrived(xdg):
    from chinchilla.ui import app as app_module

    provider = SlowProvider()
    app, _ = _app(provider)
    monkeypatch_event = provider.release
    monkeypatch_event.set()
    app.submit("translate this")

    from chinchilla.ui.gtk import Gtk

    while Gtk.events_pending():
        Gtk.main_iteration_do(False)

    app.stop_turn()

    assert app.busy is False
    assert app.window.content.status_label.get_text().lower().startswith("stop")
    assert app.window.content.stop_button.get_visible() is False
    assert app.window.content.send_button.get_sensitive()


def test_retry_asks_the_last_question_again(xdg):
    app, provider = _app()
    _seed_capture(app)
    app.submit("explain the diagram")
    _drain(app)
    turns_before = len(app.session.turns)
    answer_before = app.session.turns[-1].text

    app.retry_last()
    _drain(app)

    assert len(provider.seen) == 2
    # The question is reused and only the answer is regenerated.
    assert [turn.role for turn in app.session.turns] == ["user", "assistant"]
    assert len(app.session.turns) == turns_before
    assert app.window.content.active_action is None
    assert app.session.turns[-1].text == answer_before


def test_retry_keeps_a_single_question_when_the_answer_stopped(xdg):
    app, provider = _app()
    _seed_capture(app)
    app.submit("keep this question")
    _drain(app)
    app.retry_last()
    _drain(app)
    app.retry_last()
    _drain(app)

    questions = [turn.text for turn in app.session.turns if turn.role == "user"]
    assert questions == ["keep this question"]
    assert len(provider.seen) == 3


def test_the_effort_choice_is_saved_and_shown(xdg):
    app, _provider = _app()
    assert app.window.content.effort_value() == "medium"

    app.set_reasoning_effort("xhigh")

    assert app.settings.reasoning_effort == "xhigh"
    assert config.load_settings().reasoning_effort == "xhigh"
    assert "xhigh" in app.window.content.status_label.get_text()

    app.new_session()
    assert app.window.content.effort_value() == "xhigh"


def test_an_unknown_effort_is_ignored(xdg):
    app, _provider = _app()

    app.set_reasoning_effort("turbo")

    assert app.settings.reasoning_effort == "medium"


class ReasoningProvider(StubProvider):
    def chat(self, messages, tools=None, stream=True):
        self.seen.append(list(messages))
        yield llm.Chunk("reasoning", text="the user wants a poem")
        yield from super().chat(messages, tools=tools, stream=stream)


def test_reasoning_reaches_the_session_file(xdg):
    app, provider = _app(ReasoningProvider())
    _seed_capture(app)
    app.submit("write a poem")
    _drain(app)

    stored = session_store.Session.load(app.session.id)
    assert stored.turns[-1].reasoning == "the user wants a poem"
    assert stored.turns[-1].text == "Hello from the stub."


def test_the_footer_says_when_copilot_is_not_signed_in(xdg):
    app, _provider = _app()
    app.settings.active_provider = "copilot"

    app.refresh_panel()

    assert app.window.content.provider_label.get_text() == "github copilot \u00b7 not signed in"


def test_the_footer_asks_for_a_model_once_copilot_is_signed_in(xdg, tmp_path, monkeypatch):
    from chinchilla.core import copilot

    path = tmp_path / "copilot.json"
    copilot.Credentials(github_token="gho_x", token="t", expires_at=9_999_999_999, login="david").save(path)
    monkeypatch.setattr(copilot.Credentials, "path", classmethod(lambda cls: path))
    app, _provider = _app()
    app.settings.active_provider = "copilot"

    app.refresh_panel()

    assert app.window.content.provider_label.get_text() == "github copilot \u00b7 pick a model"

    app.settings.providers["copilot"].model = "claude-sonnet-5"
    app.refresh_panel()

    assert app.window.content.provider_label.get_text() == "github copilot \u00b7 claude-sonnet-5"
