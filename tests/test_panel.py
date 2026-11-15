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


def _knob_side(chip):
    return chip._track.query_child_packing(chip._knob).pack_type


def test_the_web_chip_moves_its_knob_to_the_side_that_matches_the_state():
    from chinchilla.ui.gtk import Gtk
    from chinchilla.ui.panel import WebChip

    seen = []
    chip = WebChip(on_change=seen.append)
    assert _knob_side(chip) == Gtk.PackType.START

    chip.set_active(True)

    assert _knob_side(chip) == Gtk.PackType.END
    assert seen == [True]

    chip.set_active(False)

    assert _knob_side(chip) == Gtk.PackType.START
    assert seen == [True, False]


def test_the_web_chip_keeps_its_knob_inside_the_track():
    from chinchilla.ui.panel import WebChip

    chip = WebChip()
    chip.set_active(True)

    assert chip._knob.get_parent() is chip._track
    assert len(chip._track.get_children()) == 1


def _labels(widget):
    from chinchilla.ui.gtk import Gtk

    found = [widget] if isinstance(widget, Gtk.Label) else []
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            found.extend(_labels(child))
    return found


def _sources_labels(content):
    return [
        label
        for label in _labels(content)
        if label.get_style_context().has_class("source-label")
    ]


def test_sources_are_clickable_links_with_a_host_hint():
    from chinchilla.core.thread import Source, Turn
    from chinchilla.ui.panel import PanelContent

    content = PanelContent()
    content.add_turn(
        Turn(
            role="assistant",
            text="see [1]",
            sources=[
                Source(
                    title="S&P 500 Index Technical Analysis",
                    url="https://www.barchart.com/stocks/quotes/%24SPX/technical-analysis",
                )
            ],
        )
    )

    labels = _sources_labels(content)
    assert len(labels) == 1
    markup = labels[0].get_label()
    assert '<a href="https://www.barchart.com/stocks/quotes/%24SPX/technical-analysis">' in markup
    assert "1. S&amp;P 500 Index Technical Analysis" in markup
    assert "www.barchart.com" in markup
    assert labels[0].get_selectable() is True


def test_a_source_without_a_title_is_not_repeated_twice():
    from chinchilla.core.thread import Source
    from chinchilla.ui.panel import source_markup

    markup = source_markup(2, Source(title="finance.yahoo.com", url="https://finance.yahoo.com/q"))

    assert markup.endswith("</a>")
    assert "+00b7" not in markup and "\u00b7" not in markup


def test_the_link_handler_ignores_anything_but_http():
    from chinchilla.core.thread import Source, Turn
    from chinchilla.ui.panel import PanelContent

    content = PanelContent()
    content.add_turn(
        Turn(
            role="assistant",
            text="x",
            sources=[Source(title="Docs", url="https://example.com/docs")],
        )
    )
    label = _sources_labels(content)[0]

    assert label.emit("activate-link", "file:///etc/passwd") is True
    assert label.emit("activate-link", "javascript:alert(1)") is True


def test_the_header_buttons_carry_their_own_size_and_colour():
    from chinchilla.ui.panel import PanelContent

    content = PanelContent()

    assert content.close_button.get_style_context().has_class("icon-close")
    assert content.settings_button.get_style_context().has_class("icon-gear")


def test_the_effort_combo_offers_the_four_levels_and_starts_medium():
    content = PanelContent()
    assert content.effort_value() == "medium"
    ids = [row[0] for row in content.effort_combo.get_model()]
    assert ids == ["low", "medium", "high", "xhigh"]


def test_set_effort_does_not_echo_back_to_the_app():
    chosen = []
    content = PanelContent(on_effort=chosen.append)
    content.set_effort("high")
    assert content.effort_value() == "high"
    assert chosen == []


def test_picking_an_effort_reports_it():
    chosen = []
    content = PanelContent(on_effort=chosen.append)
    content.effort_combo.set_active_id("xhigh")
    assert chosen == ["xhigh"]


def test_an_unknown_effort_falls_back_to_the_default():
    content = PanelContent()
    content.set_effort("turbo")
    assert content.effort_value() == "medium"
