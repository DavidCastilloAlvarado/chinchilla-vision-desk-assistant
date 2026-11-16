import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or sys.platform == "darwin"  # Quartz always has a display
    ),
    reason="needs a display to build GTK objects",
)


def _pane(sessions=None, active_id="", picks=None, news=None):
    from chinchilla.ui.sessions import SessionsPane, demo_sessions

    picked = picks if picks is not None else []
    created = news if news is not None else []
    pane = SessionsPane(picked.append, lambda: created.append(True), active_id)
    pane.sessions = sessions if sessions is not None else demo_sessions()
    pane._refill()
    return pane


def _row_labels(widget):
    """Every label inside a row, at any depth."""
    found = []
    if hasattr(widget, "get_text"):
        found.append(widget.get_text())
    if isinstance(widget, __import__("gi").repository.Gtk.Container):
        for child in widget.get_children():
            found.extend(_row_labels(child))
    return found


def test_rows_follow_the_stored_sessions():
    pane = _pane()

    rows = pane.listbox.get_children()
    assert len(rows) == 3
    assert pane.empty_label.get_visible() is False


def test_search_filters_by_title_and_text():
    pane = _pane()
    pane.search.set_text("grammar")
    pane._refill()
    assert len(pane.listbox.get_children()) == 1

    pane.search.set_text("dependency array")
    pane._refill()
    assert len(pane.listbox.get_children()) == 1

    pane.search.set_text("nothing matches this")
    pane._refill()
    assert pane.listbox.get_children() == []
    assert pane.empty_label.get_visible() is True


def test_row_preview_prefers_the_user_question():
    pane = _pane()
    previews = [
        label
        for label in _row_labels(pane.listbox.get_children()[1])
        if "captures" in label
    ]
    assert previews and "why does this effect loop?" in previews[0]


def test_picking_a_row_reports_the_session_id():
    from chinchilla.ui.sessions import demo_sessions

    picked = []
    pane = _pane(picks=picked)
    pane._on_row_clicked(None, demo_sessions()[0].id)

    assert picked == [demo_sessions()[0].id]


def test_new_session_button_reports_the_request():
    created = []
    pane = _pane(news=created)
    pane._on_new_clicked(None)

    assert created == [True]


def test_meta_line_mentions_captures_and_web():
    from chinchilla.ui.sessions import _meta

    sessions = _pane().sessions
    assert "2 shots" in _meta(sessions[1])
    assert "web" in _meta(sessions[2])


def test_sessions_render_writes_a_png(xdg, tmp_path):
    from chinchilla.cli import main

    target = tmp_path / "sessions.png"
    assert main(["sessions", "list", "--render", str(target), "--demo"]) == 0
    assert target.is_file() and target.stat().st_size > 4000

def test_the_popover_maps_its_rows_the_first_time_it_opens():
    """Without show_all the popover is an empty 76x52 sliver."""
    from chinchilla.ui.sessions import SessionsPopover, demo_sessions

    popover = SessionsPopover(lambda _sid: None, lambda: None)
    popover.pane.sessions = demo_sessions()
    popover.pane._refill()
    try:
        popover.popup()
        assert popover.pane.get_visible() is True
        assert popover.pane.new_button.get_visible() is True
        assert popover.pane.search.get_visible() is True
        assert popover.pane.listbox.get_children()[0].get_visible() is True
    finally:
        popover.popdown()
        popover.destroy()


def test_the_selector_forwards_a_pick_instead_of_calling_itself():
    picked = []
    from chinchilla.ui.sessions import SessionsPopover, demo_sessions

    popover = SessionsPopover(picked.append, lambda: None)
    popover.pane.sessions = demo_sessions()
    popover.pane._refill()
    popover.pane.listbox.get_children()[0].get_child().clicked()

    assert picked == [demo_sessions()[0].id]
