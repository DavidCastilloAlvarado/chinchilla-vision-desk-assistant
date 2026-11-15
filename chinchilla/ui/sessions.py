"""Session selector: search, recent conversations and a new-session button.

Matches screen 05 of the wireframe: a popover hanging off the panel's session
title, with a header, a search field, rows carrying the first capture, the
title and the last question, and a footer with the count.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .. import paths
from ..store import session as session_store
from . import theme
from .gtk import Gtk, Pango

POPOVER_WIDTH = 320
ROW_HEIGHT = 42


def _ago(timestamp: float) -> str:
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _meta(session: session_store.Session) -> str:
    turns = session.turn_count()
    shots = len(session.captures)
    parts = [_ago(session.updated_at), f"{turns} turn{'s' if turns != 1 else ''}"]
    if shots:
        parts.append(f"{shots} shot{'s' if shots != 1 else ''}")
    if session.web_enabled:
        parts.append("web")
    return "  \u00b7  ".join(parts)


def _detail(session: session_store.Session) -> str:
    """`2 captures · "the last thing I asked"`, like the wireframe row."""
    shots = len(session.captures)
    parts = [f"{shots} capture{'s' if shots != 1 else ''}"] if shots else ["no cut"]
    preview = session.preview(46)
    if preview:
        parts.append(f"\u201c{preview}\u201d")
    return " \u00b7 ".join(parts)


def _thumb(session: session_store.Session) -> Gtk.Widget:
    """First capture of the thread, or an empty plate when it has none."""
    capture = session.captures[0] if session.captures else None
    path = capture.path if capture is not None else ""
    image = None
    if path and Path(path).is_file():
        from .panel import load_image

        image = load_image(path, 21)
    if image is not None:
        image.get_style_context().add_class("crop-mini")
        image.set_size_request(30, 21)
        return image
    plate = Gtk.Box()
    plate.get_style_context().add_class("card")
    plate.set_size_request(30, 21)
    return plate


class SessionsPane(Gtk.Box):
    """Lists stored conversations; picking one or creating one is a callback."""

    def __init__(
        self,
        on_pick: Callable[[str], None],
        on_new: Callable[[], None],
        active_id: str = "",
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        theme.apply_css()
        self.on_pick = on_pick
        self.on_new = on_new
        self.active_id = active_id
        self.sessions: list[session_store.Session] = []
        self.set_size_request(POPOVER_WIDTH, 400)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        head.get_style_context().add_class("pop-head")
        title = Gtk.Label(label="SESSIONS")
        title.set_xalign(0)
        title.get_style_context().add_class("pop-title")
        head.pack_start(title, False, False, 0)
        self.new_button = Gtk.Button(label="+ New session")
        self.new_button.set_relief(Gtk.ReliefStyle.NONE)
        self.new_button.get_style_context().add_class("pop-new")
        self.new_button.set_tooltip_text("Start a clean thread (Ctrl+N)")
        self.new_button.connect("clicked", self._on_new_clicked)
        head.pack_end(self.new_button, False, False, 0)
        self.pack_start(head, False, False, 0)

        self.search = Gtk.Entry()
        self.search.set_placeholder_text("Search titles and messages\u2026")
        self.search.get_style_context().add_class("sp-search")
        self.search.connect("changed", lambda *_: self._refill())
        search_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_wrap.set_margin_start(9)
        search_wrap.set_margin_end(9)
        search_wrap.set_margin_top(8)
        search_wrap.set_margin_bottom(6)
        search_wrap.pack_start(self.search, True, True, 0)
        self.pack_start(search_wrap, False, False, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_size_request(-1, 260)
        scroller.add(self.listbox)
        self.pack_start(scroller, True, True, 0)

        self.empty_label = Gtk.Label(label="No conversation yet")
        self.empty_label.set_xalign(0)
        self.empty_label.set_no_show_all(True)
        self.empty_label.get_style_context().add_class("muted-label")
        self.empty_label.set_margin_start(11)
        self.empty_label.set_margin_bottom(8)
        self.pack_start(self.empty_label, False, False, 0)

        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        foot.get_style_context().add_class("sp-foot")
        self.count_label = Gtk.Label(label="")
        self.count_label.set_xalign(0)
        self.count_label.get_style_context().add_class("sp-foot-text")
        foot.pack_start(self.count_label, False, False, 0)
        where = Gtk.Label(label=f"Stored in {paths.data_dir()}")
        where.set_xalign(1)
        where.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        where.get_style_context().add_class("sp-foot-text")
        foot.pack_end(where, True, True, 0)
        self.pack_start(foot, False, False, 0)

    # ------------------------------------------------------------------ state

    def set_active(self, active_id: str) -> None:
        self.active_id = active_id
        self._refill()

    def reload(self) -> None:
        self.sessions = session_store.list_sessions()
        self._refill()

    def visible_sessions(self) -> list[session_store.Session]:
        query = self.search.get_text().strip().lower()
        if not query:
            return self.sessions
        return [session for session in self.sessions if query in self._haystack(session)]

    @staticmethod
    def _haystack(session: session_store.Session) -> str:
        parts = [session.title, session.preview()]
        parts.extend(turn.text for turn in session.turns if turn.text)
        return "\n".join(parts).lower()

    def _refill(self) -> None:
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        shown = self.visible_sessions()
        for session in shown:
            self.listbox.add(self._row(session))
        self.listbox.show_all()
        self.empty_label.set_visible(not shown)
        self.count_label.set_text(f"{len(self.sessions)} session{'s' if len(self.sessions) != 1 else ''}")

    def _row(self, session: session_store.Session) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.session_id = session.id
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("sp-row")
        if session.id == self.active_id:
            button.get_style_context().add_class("on")
        button.connect("clicked", self._on_row_clicked, session.id)

        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        line.pack_start(_thumb(session), False, False, 0)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        meta.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label=session.title or "Untitled")
        title.set_xalign(0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.get_style_context().add_class("sp-title")
        if session.id == self.active_id:
            title.get_style_context().add_class("active-session")
        meta.pack_start(title, False, False, 0)
        detail = Gtk.Label(label=_detail(session))
        detail.set_xalign(0)
        detail.set_ellipsize(Pango.EllipsizeMode.END)
        detail.get_style_context().add_class("sp-preview")
        meta.pack_start(detail, False, False, 0)
        line.pack_start(meta, True, True, 0)

        stamp = Gtk.Label(label=_ago(session.updated_at))
        stamp.set_valign(Gtk.Align.START)
        stamp.get_style_context().add_class("sp-time")
        line.pack_end(stamp, False, False, 0)

        button.add(line)
        row.add(button)
        return row

    # -------------------------------------------------------------- callbacks

    def _on_row_clicked(self, _button: Gtk.Button | None, session_id: str) -> None:
        self.on_pick(session_id)

    def _on_new_clicked(self, _button: Gtk.Button | None) -> None:
        self.on_new()


def demo_sessions() -> list[session_store.Session]:
    """Sample rows for renders and tests; nothing is written to disk."""
    now = time.time()
    return [
        session_store.Session(
            id="demo-train",
            title="Deutsche Bahn ticket",
            updated_at=now - 90,
            turns=[session_store.Turn(role="user", text="where does the train leave from?")],
            captures=[session_store.Capture(id="c1", path="captures/c1.jpg")],
        ),
        session_store.Session(
            id="demo-hook",
            title="React hook error",
            updated_at=now - 5400,
            turns=[
                session_store.Turn(role="user", text="why does this effect loop?"),
                session_store.Turn(role="assistant", text="the dependency array is missing"),
            ],
            captures=[
                session_store.Capture(id="c2", path="captures/c2.jpg"),
                session_store.Capture(id="c3", path="captures/c3.jpg"),
            ],
        ),
        session_store.Session(
            id="demo-letter",
            title="Grammar: cover letter",
            updated_at=now - 172800,
            turns=[session_store.Turn(role="user", text="fix the grammar in my cover letter")],
            web_enabled=True,
        ),
    ]


class SessionsPopover(Gtk.Popover):
    """The pane attached to the panel's session title."""

    def __init__(
        self,
        on_pick: Callable[[str], None],
        on_new: Callable[[], None],
        active_id: str = "",
    ) -> None:
        super().__init__()
        self.set_position(Gtk.PositionType.BOTTOM)
        self._on_pick = on_pick
        self._on_new = on_new
        self.pane = SessionsPane(self._pick, self._new, active_id)
        self.add(self.pane)

    def _pick(self, session_id: str) -> None:
        self.popdown()
        self._on_pick(session_id)

    def _new(self) -> None:
        self.popdown()
        self._on_new()

    def reload(self) -> None:
        self.pane.reload()

    def set_active(self, active_id: str) -> None:
        self.pane.set_active(active_id)
