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
    content.entry.get_buffer().set_text("  hello  ")
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
