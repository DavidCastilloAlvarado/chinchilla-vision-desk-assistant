"""Session selector: search, recent conversations and a new-session button."""

from __future__ import annotations

import time
from typing import Callable

from ..store import session as session_store
from . import theme
from .gtk import Gtk, Pango

SIDE_MARGIN = 10


def _ago(timestamp: float) -> str:
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def _meta(session: session_store.Session) -> str:
    turns = session.turn_count()
    shots = len(session.captures)
    parts = [_ago(session.updated_at), f"{turns} turn{'s' if turns != 1 else ''}"]
    if shots:
        parts.append(f"{shots} shot{'s' if shots != 1 else ''}")
    if session.web_enabled:
        parts.append("web")
    return "  \u00b7  ".join(parts)


class SessionsPane(Gtk.Box):
    """Lists stored conversations; picking one or creating one is a callback."""

    def __init__(
        self,
        on_pick: Callable[[str], None],
        on_new: Callable[[], None],
        active_id: str = "",
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        theme.apply_css()
        self.on_pick = on_pick
        self.on_new = on_new
        self.active_id = active_id
        self.sessions: list[session_store.Session] = []
        self.set_size_request(360, 420)
        self.set_margin_start(SIDE_MARGIN)
        self.set_margin_end(SIDE_MARGIN)
        self.set_margin_top(SIDE_MARGIN)
        self.set_margin_bottom(SIDE_MARGIN)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search conversations")
        self.search.connect("search-changed", lambda *_: self._refill())
        self.pack_start(self.search, False, False, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_size_request(-1, 280)
        scroller.add(self.listbox)
        self.pack_start(scroller, True, True, 0)

        self.empty_label = Gtk.Label(label="No conversation yet")
        self.empty_label.set_xalign(0)
        self.empty_label.set_no_show_all(True)
        self.empty_label.get_style_context().add_class("muted-label")
        self.pack_start(self.empty_label, False, False, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.new_button = Gtk.Button(label="+ New session")
        self.new_button.get_style_context().add_class("accent-button")
        self.new_button.connect("clicked", self._on_new_clicked)
        footer.pack_start(self.new_button, True, True, 0)
        self.pack_start(footer, False, False, 0)

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

    def _row(self, session: session_store.Session) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("session-row")
        button.connect("clicked", self._on_row_clicked, session.id)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        title = Gtk.Label(label=session.title or "Untitled")
        title.set_xalign(0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        if session.id == self.active_id:
            title.get_style_context().add_class("active-session")
        box.pack_start(title, False, False, 0)

        meta = Gtk.Label(label=_meta(session))
        meta.set_xalign(0)
        meta.get_style_context().add_class("muted-label")
        box.pack_start(meta, False, False, 0)

        preview = session.preview()
        if preview:
            snippet = Gtk.Label(label=preview)
            snippet.set_xalign(0)
            snippet.set_ellipsize(Pango.EllipsizeMode.END)
            snippet.get_style_context().add_class("muted-label")
            box.pack_start(snippet, False, False, 0)

        button.add(box)
        row.add(button)
        return row

    # -------------------------------------------------------------- callbacks

    def _on_row_clicked(self, _button: Gtk.Button, session_id: str) -> None:
        self.on_pick(session_id)

    def _on_new_clicked(self, _button: Gtk.Button) -> None:
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
        self.pane = SessionsPane(self._pick, self._new, active_id)
        self.add(self.pane)

    def _pick(self, session_id: str) -> None:
        self.popdown()
        self.pane.on_pick(session_id)

    def _new(self) -> None:
        self.popdown()
        self.pane.on_new()

    def reload(self) -> None:
        self.pane.reload()

    def set_active(self, active_id: str) -> None:
        self.pane.set_active(active_id)
