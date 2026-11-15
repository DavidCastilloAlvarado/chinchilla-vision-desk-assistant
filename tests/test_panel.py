import os

import pytest

from chinchilla.ui.panel import PanelContent, demo_content, to_pango

pytestmark = pytest.mark.skipif(
    not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
    reason="needs a display to build GTK objects",
)


def test_markup_is_escaped_before_formatting():
    markup = to_pango("<script>alert(1)</script> **bold** `code`")
    assert "&lt;script&gt;" in markup
    assert "<b>bold</b>" in markup
    assert "<tt>code</tt>" in markup


def test_bullets_are_kept():
    assert "  \u2022 one" in to_pango("- one")


def test_quick_action_pill_reports_its_id():
    clicks = []
    content = PanelContent(on_prompt=lambda action, _text: clicks.append(action))
    content.action_buttons["translate"].clicked()
    assert clicks == ["translate"]


def test_send_button_passes_the_composer_text():
    sent = []
    content = PanelContent(on_send=sent.append)
    content.entry.set_text("  hello  ")
    content.send_button.clicked()
    assert sent == ["hello"]
    assert content.composer_text() == ""


def test_streaming_appends_and_finishes():
    content = PanelContent()
    content.start_assistant_turn("explain")
    content.append_text("Hola ")
    content.append_text("mundo")
    assert content._streaming_text == "Hola mundo"
    content.finish_assistant_turn()
    assert content._streaming_label is None


def test_panel_renders_a_full_frame(tmp_path):
    from PIL import Image

    from chinchilla.ui.panel import PANEL_WIDTH
    from chinchilla.ui.snapshot import offscreen_pixbuf, save_pixbuf

    content = demo_content()
    pixbuf = offscreen_pixbuf(content, PANEL_WIDTH, 760)
    path = save_pixbuf(pixbuf, tmp_path / "panel.png")
    image = Image.open(path).convert("RGB")
    assert image.width == PANEL_WIDTH
    assert image.height >= 700
    colours = image.getcolors(maxcolors=200000)
    assert len(colours) > 50
    accent = [
        colour
        for _count, colour in colours
        if colour[0] > 200 and 150 < colour[1] < 200 and colour[2] < 110
    ]
    assert accent, "the accent coloured send button should be visible"


def test_usage_line_under_the_composer():
    from chinchilla.core.thread import Turn, Usage
    from chinchilla.ui import panel as panel_ui

    content = panel_ui.PanelContent()
    assert content.usage_label.get_text() == ""

    content.set_usage(Usage(input_tokens=12400, output_tokens=1800, cached_tokens=9300))
    assert content.usage_label.get_text() == "in 12.4k · out 1.8k · cache 75%"

    content.set_session(
        title="Counted",
        turns=[
            Turn(role="user", text="hi"),
            Turn(role="assistant", text="hello", usage=Usage(500, 40, 0)),
            Turn(role="assistant", text="again", usage=Usage(500, 60, 250)),
        ],
    )
    assert content.usage_label.get_text() == "in 1.0k · out 100 · cache 25%"


def _press(button: int = 1):
    from chinchilla.ui.gtk import Gdk

    event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
    event.button = button
    event.x_root = 40
    event.y_root = 40
    event.time = 0
    return event


def test_clicking_the_title_does_not_start_a_window_drag():
    """The title opens the session selector; dragging is for the header."""
    from chinchilla.ui.panel import PanelWindow

    window = PanelWindow()
    drags = []
    window.begin_move_drag = lambda *args: drags.append(args)  # type: ignore[method-assign]
    try:
        window.content.title_button.emit("button-press-event", _press())
    finally:
        window.destroy()

    assert drags == []


def test_dragging_the_header_still_moves_the_window():
    from chinchilla.ui.panel import PanelWindow

    window = PanelWindow()
    drags = []
    window.begin_move_drag = lambda *args: drags.append(args)  # type: ignore[method-assign]
    try:
        window.content.header.emit("button-press-event", _press())
    finally:
        window.destroy()

    assert len(drags) == 1


def _key(keyval: int):
    from chinchilla.ui.gtk import Gdk

    event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
    event.keyval = keyval
    event.state = Gdk.ModifierType(0)
    return event


def test_digits_run_the_quick_actions_when_the_composer_is_not_focused():
    from chinchilla.ui.gtk import Gdk
    from chinchilla.ui.panel import PanelWindow

    prompts = []
    window = PanelWindow(actions=[("translate", "Translate"), ("explain", "Explain")])
    window.content.on_prompt = lambda action_id, _label=None: prompts.append(action_id)
    window.show_all()
    try:
        window.set_focus(None)
        window.emit("key-press-event", _key(Gdk.KEY_2))
    finally:
        window.destroy()

    assert prompts == ["explain"]


def test_digits_typed_in_the_composer_stay_text():
    from chinchilla.ui.gtk import Gdk
    from chinchilla.ui.panel import PanelWindow

    prompts = []
    window = PanelWindow(actions=[("translate", "Translate")])
    window.content.on_prompt = lambda action_id, _label=None: prompts.append(action_id)
    window.show_all()
    try:
        window.content.entry.grab_focus()
        window.emit("key-press-event", _key(Gdk.KEY_1))
        typing = window._typing()
    finally:
        window.destroy()

    assert typing is True
    assert prompts == []


def test_busy_panel_offers_stop_and_locks_the_actions():
    from chinchilla.ui.panel import PanelContent

    content = PanelContent(actions=[("translate", "Translate")])
    content.set_busy(True)

    assert content.stop_button.get_visible() is True
    assert content.send_button.get_sensitive() is False
    assert content.action_buttons["translate"].get_sensitive() is False

    content.set_busy(False)

    assert content.stop_button.get_visible() is False
    assert content.send_button.get_sensitive() is True


def test_the_composer_is_a_frameless_entry_inside_the_ask_box():
    from chinchilla.ui.panel import PanelContent

    content = PanelContent()

    assert content.entry.get_has_frame() is False
    assert content.entry.get_placeholder_text().startswith("Ask anything")
    assert content.entry.get_parent() is content.ask_box
    assert content.ask_box.get_size_request() == (-1, 34)
