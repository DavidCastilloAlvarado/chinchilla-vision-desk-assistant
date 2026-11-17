"""The response panel: session header, quick actions, thread and composer.

The layout follows ``docs/wireframes/wireframes.html`` (screens 02-05): a
header with the capture stack and the session title, a chip row with web
search / capture / new session, three quick-action tiles, the thread, an ask
field and a footer with the provider and the turn buttons.
"""

from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Callable

from .. import system
from ..core.search import host_of
from ..store import config
from ..core.thread import Capture, Source, Turn, Usage
from . import theme
from .gtk import Gdk, GdkPixbuf, GLib, Gtk, Pango
from .markdown import to_pango  # noqa: F401  kept for single-label callers
from .richtext import MarkdownView
from .widgets import place_knob

PANEL_WIDTH = 404
PADDING = 12
# room for the cuts of one turn: the panel minus its padding, the avatar column
# and some slack for the bubble's CSS and the overlay scrollbar
CROP_ROW_WIDTH = PANEL_WIDTH - 2 * PADDING - 17 - 8 - 35
CROP_SPACING = 6
CROP_HEIGHT = 50

DEFAULT_ACTIONS = [
    ("translate", "Translate"),
    ("explain", "Explain"),
    ("grammar", "Fix grammar"),
]

# the composer grows with its text up to this many lines, then scrolls
COMPOSER_MAX_LINES = 10


def clock(timestamp: float) -> str:
    return time.strftime("%H:%M", time.localtime(timestamp))


def source_markup(index: int, source: Source) -> str:
    """`1. title · host`, with the title as a link the user can click or select."""
    title = html.escape(source.title or source.url or "source")
    if not source.url:
        return f"{index}. {title}"
    url = html.escape(source.url, quote=True)
    link = f'<a href="{url}">{index}. {title}</a>'
    host = host_of(source.url)
    if not host or host.lower() == (source.title or "").strip().lower():
        return link
    return (
        f'{link}<span size="small" foreground="#6f7a8e"> \u00b7 {html.escape(host)}</span>'
    )


def short_count(tokens: int) -> str:
    if tokens >= 100000:
        return f"{tokens / 1000:.0f}k"
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return str(tokens)


def usage_text(usage: Usage | None) -> str:
    """One line for under the composer: in, out and the share served from cache."""
    if usage is None or usage.is_empty:
        return ""
    return (
        f"in {short_count(usage.input_tokens)}"
        f" \u00b7 out {short_count(usage.output_tokens)}"
        f" \u00b7 cache {usage.cached_ratio * 100:.0f}%"
    )


def fit_size(width: int, height: int, max_height: int, max_width: int | None = None) -> tuple[int, int]:
    """Scale to `max_height`, then shrink further if that is wider than `max_width`.

    Scaling by height alone made a flat strip (1684x156 is 540 px wide at 50
    px tall) wider than the panel, and GTK grew the window off the screen.
    """
    scale = max_height / max(1, height)
    if max_width is not None and width * scale > max_width:
        scale = max_width / max(1, width)
    return max(1, round(width * scale)), max(1, round(height * scale))


def load_image(path: str, height: int = 34, max_width: int | None = None) -> Gtk.Image | None:
    if not path or not Path(path).is_file():
        return None
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    except Exception:
        return None
    width, height = fit_size(pixbuf.get_width(), pixbuf.get_height(), height, max_width)
    scaled = pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    return Gtk.Image.new_from_pixbuf(scaled)


def load_thumbnail(path: str, size: int = 40, max_width: int | None = None) -> Gtk.Widget | None:
    """Small preview of a capture, used in the header and the thread."""
    image = load_image(path, size, max_width)
    if image is not None:
        image.get_style_context().add_class("thumb")
    return image


class WebChip(Gtk.Button):
    """The `Web search` chip, with a drawn switch instead of a native one.

    `GtkSwitch` cannot be styled small enough for the chip row, so the track and
    the knob are plain boxes and the whole button is the control.
    """

    def __init__(self, on_change: Callable[[bool], None] | None = None) -> None:
        super().__init__()
        self._active = False
        self._on_change = on_change
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_tooltip_text("Let the agent search the web (Ctrl+W)")
        self.get_style_context().add_class("tool")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._track = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._track.get_style_context().add_class("tool-switch")
        self._track.set_valign(Gtk.Align.CENTER)
        self._knob = Gtk.Box()
        self._knob.get_style_context().add_class("tool-knob")
        row.pack_start(self._track, False, False, 0)
        row.pack_start(Gtk.Label(label="Web search"), False, False, 0)
        self.add(row)
        self.connect("clicked", lambda *_: self.set_active(not self._active))
        self._render()

    def _render(self) -> None:
        context = self.get_style_context()
        if self._active:
            context.add_class("on")
            self._track.get_style_context().add_class("on")
        else:
            context.remove_class("on")
            self._track.get_style_context().remove_class("on")
        place_knob(self._track, self._knob, self._active)

    def get_active(self) -> bool:
        return self._active

    def set_active(self, active: bool, notify: bool = True) -> None:
        active = bool(active)
        changed = active != self._active
        self._active = active
        self._render()
        if changed and notify and self._on_change is not None:
            self._on_change(active)


class PanelContent(Gtk.Box):
    """Everything inside the panel, kept separate so it can be rendered alone."""

    def __init__(
        self,
        actions: list[tuple[str, str]] | None = None,
        on_prompt: Callable[[str, str | None], None] | None = None,
        on_capture: Callable[[], None] | None = None,
        on_new_session: Callable[[], None] | None = None,
        on_sessions: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_web: Callable[[bool], None] | None = None,
        on_send: Callable[[str], None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_retry: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_effort: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_name("chinchilla-panel")
        self.get_style_context().add_class("panel-root")

        self.on_prompt = on_prompt
        self.on_capture = on_capture
        self.on_new_session = on_new_session
        self.on_sessions = on_sessions
        self.on_settings = on_settings
        self.on_web = on_web
        self.on_send = on_send
        self.on_close = on_close
        self.on_retry = on_retry
        self.on_stop = on_stop
        self.on_effort = on_effort
        self._loading_effort = False

        self._actions = list(actions or DEFAULT_ACTIONS)
        self._captures: list[Capture] = []
        self._turns: list[Turn] = []
        self._busy = False
        self._last_answer = ""
        self._streaming_label: Gtk.Label | None = None
        self._streaming_text = ""
        self._streaming_turn: Gtk.Box | None = None
        self._reasoning_text = ""
        self._reasoning_expander: Gtk.Expander | None = None

        self._build_header()
        self._build_tools()
        self._build_actions()
        self._build_thread()
        self._build_composer()
        self._build_footer()
        self._update_subline()

    # ------------------------------------------------------------------ build

    def _build_header(self) -> None:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.get_style_context().add_class("panel-head")
        self.header = header

        self.thumb_stack = Gtk.Overlay()
        self.thumb_stack.set_size_request(58, 34)
        self.thumb_stack.set_valign(Gtk.Align.START)
        self.thumb_stack.set_tooltip_text("Cuts in this session")
        behind = Gtk.Box()
        behind.get_style_context().add_class("thumb-behind")
        behind.set_size_request(46, 32)
        behind.set_halign(Gtk.Align.START)
        behind.set_valign(Gtk.Align.START)
        self.thumb_stack.add(behind)
        self._thumbs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self._thumbs.set_halign(Gtk.Align.START)
        self._thumbs.set_valign(Gtk.Align.START)
        self._thumbs.set_margin_start(10)
        self._thumbs.set_margin_top(2)
        self.thumb_stack.add_overlay(self._thumbs)
        self.thumb_count = Gtk.Label(label="")
        self.thumb_count.get_style_context().add_class("thumb-count")
        self.thumb_count.set_halign(Gtk.Align.END)
        self.thumb_count.set_valign(Gtk.Align.END)
        self.thumb_count.set_no_show_all(True)
        self.thumb_stack.add_overlay(self.thumb_count)
        header.pack_start(self.thumb_stack, False, False, 0)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.title_button = Gtk.Button()
        self.title_button.set_relief(Gtk.ReliefStyle.NONE)
        self.title_button.get_style_context().add_class("head-title")
        self.title_button.set_tooltip_text("Switch session (Ctrl+S)")
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        self.title_label = Gtk.Label(label="New session")
        self.title_label.set_xalign(0)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.title_label.set_max_width_chars(26)
        self.title_label.get_style_context().add_class("head-title")
        title_row.pack_start(self.title_label, False, False, 0)
        caret = Gtk.Label(label="\u25be")
        caret.get_style_context().add_class("head-caret")
        title_row.pack_start(caret, False, False, 0)
        self.title_button.add(title_row)
        self.title_button.set_halign(Gtk.Align.START)
        self.title_button.connect("clicked", lambda *_: self._emit(self.on_sessions))
        titles.pack_start(self.title_button, False, False, 0)

        self.sub_label = Gtk.Label(label="")
        self.sub_label.set_xalign(0)
        self.sub_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub_label.get_style_context().add_class("head-sub")
        titles.pack_start(self.sub_label, False, False, 0)
        header.pack_start(titles, True, True, 0)

        self.settings_button = self._icon_button("\u2699", "Settings", self.on_settings)
        self.settings_button.get_style_context().add_class("icon-gear")
        header.pack_end(self.settings_button, False, False, 0)
        self.close_button = self._icon_button("\u00d7", "Hide (Esc)", self.on_close)
        self.close_button.get_style_context().add_class("icon-close")
        header.pack_end(self.close_button, False, False, 0)

        self.pack_start(header, False, False, 0)

    def _icon_button(self, glyph: str, tooltip: str, callback) -> Gtk.Button:
        button = Gtk.Button(label=glyph)
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("icon-btn")
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_: self._emit(callback))
        return button

    def _build_tools(self) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.get_style_context().add_class("toolrow")

        self.web_switch = WebChip(on_change=self._on_web_change)
        row.pack_start(self.web_switch, False, False, 0)

        self.capture_button = self._chip("+", "Capture", "Ctrl R")
        self.capture_button.set_tooltip_text("Add another screen cut (Ctrl+R)")
        self.capture_button.connect("clicked", lambda *_: self._emit(self.on_capture))
        row.pack_start(self.capture_button, False, False, 0)

        spacer = Gtk.Box()
        row.pack_start(spacer, True, True, 0)

        self.new_button = self._chip("+", "New session", "")
        self.new_button.set_tooltip_text("Start a clean thread (Ctrl+N)")
        self.new_button.connect("clicked", lambda *_: self._emit(self.on_new_session))
        row.pack_end(self.new_button, False, False, 0)

        self.pack_start(row, False, False, 0)

    def _chip(self, glyph: str, text: str, shortcut: str) -> Gtk.Button:
        button = Gtk.Button()
        button.set_relief(Gtk.ReliefStyle.NONE)
        button.get_style_context().add_class("tool")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        plus = Gtk.Label(label=glyph)
        plus.get_style_context().add_class("tool-plus")
        row.pack_start(plus, False, False, 0)
        row.pack_start(Gtk.Label(label=text), False, False, 0)
        if shortcut:
            key = Gtk.Label(label=shortcut)
            key.get_style_context().add_class("tool-key")
            row.pack_start(key, False, False, 0)
        button.add(row)
        return button

    def _build_actions(self) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        row.set_homogeneous(True)
        row.set_margin_start(PADDING)
        row.set_margin_end(PADDING)
        row.set_margin_top(9)
        self.action_buttons: dict[str, Gtk.Button] = {}
        self.active_action: str | None = None
        for index, (action_id, title) in enumerate(self._actions, start=1):
            button = Gtk.Button()
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.get_style_context().add_class("act")
            button.get_style_context().add_class(f"act-{action_id}")
            button.set_tooltip_text(f"{title} (key {index})")

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            glyph = Gtk.Box()
            glyph.get_style_context().add_class("glyph")
            glyph.get_style_context().add_class(f"glyph-{action_id}")
            glyph.set_valign(Gtk.Align.CENTER)
            top.pack_start(glyph, False, False, 0)
            key = Gtk.Label(label=str(index))
            key.get_style_context().add_class("act-key")
            key.set_halign(Gtk.Align.END)
            key.set_hexpand(True)
            top.pack_end(key, False, False, 0)
            box.pack_start(top, False, False, 0)
            name = Gtk.Label(label=title)
            name.set_xalign(0)
            name.get_style_context().add_class("act-name")
            box.pack_start(name, False, False, 0)
            button.add(box)

            button.connect("clicked", self._on_action, action_id)
            row.pack_start(button, True, True, 0)
            self.action_buttons[action_id] = button
        self.actions_row = row
        self.pack_start(row, False, False, 0)

    def _build_thread(self) -> None:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_margin_start(PADDING)
        scroll.set_margin_end(PADDING)
        scroll.set_margin_top(11)
        scroll.set_overlay_scrolling(True)
        scroll.set_size_request(-1, 200)
        self.thread = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        self.thread.set_valign(Gtk.Align.START)
        scroll.add(self.thread)
        self.scroll = scroll
        self.pack_start(scroll, True, True, 0)

    def _build_composer(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(PADDING)
        box.set_margin_end(PADDING)
        box.set_margin_top(10)

        self.ask_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.ask_box.get_style_context().add_class("ask")
        self.ask_box.set_size_request(-1, 34)

        # a text view, not an entry: questions span lines, and the box grows
        # with them up to COMPOSER_MAX_LINES before it scrolls
        self.composer = Gtk.TextView()
        self.composer.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.composer.set_accepts_tab(False)
        self.composer.set_top_margin(8)
        self.composer.set_bottom_margin(8)
        self.composer.get_style_context().add_class("ask-input")
        self.composer.connect("key-press-event", self._on_composer_key)
        self.composer.connect("focus-in-event", lambda *_: self._sync_ask_state())
        self.composer.connect("focus-out-event", lambda *_: self._sync_ask_state())
        self.composer.get_buffer().connect("changed", lambda *_: self._sync_ask_state())

        self.composer_scroll = Gtk.ScrolledWindow()
        self.composer_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.composer_scroll.set_propagate_natural_height(True)
        self.composer_scroll.set_max_content_height(self._composer_max_height())
        self.composer_scroll.add(self.composer)

        self.placeholder = Gtk.Label(label="Ask anything about this capture\u2026")
        self.placeholder.set_xalign(0)
        self.placeholder.set_halign(Gtk.Align.START)
        self.placeholder.set_valign(Gtk.Align.START)
        self.placeholder.set_margin_top(8)
        self.placeholder.get_style_context().add_class("ask-placeholder")
        # shown only by _sync_ask_state, not by every show_all() of the panel
        self.placeholder.set_no_show_all(True)
        composer_stack = Gtk.Overlay()
        composer_stack.add(self.composer_scroll)
        composer_stack.add_overlay(self.placeholder)
        # clicks on the hint reach the text view underneath
        composer_stack.set_overlay_pass_through(self.placeholder, True)
        self.ask_box.pack_start(composer_stack, True, True, 0)

        self.send_button = Gtk.Button(label="\u21b5")
        self.send_button.set_relief(Gtk.ReliefStyle.NONE)
        self.send_button.get_style_context().add_class("send-btn")
        # stays on the last line while the box grows, like a chat app
        self.send_button.set_valign(Gtk.Align.END)
        self.send_button.set_margin_bottom(5)
        self.send_button.set_size_request(24, 24)
        self.send_button.set_tooltip_text("Send (Enter) \u00b7 new line (Shift+Enter)")
        self.send_button.connect("clicked", lambda *_: self._submit())
        self.ask_box.pack_end(self.send_button, False, False, 0)
        box.pack_start(self.ask_box, False, False, 0)

        self._sync_ask_state()

        usage_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.usage_label = Gtk.Label(label="")
        self.usage_label.set_xalign(1)
        self.usage_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.usage_label.get_style_context().add_class("foot-usage")
        usage_row.pack_end(self.usage_label, False, False, 0)
        box.pack_start(usage_row, False, False, 0)
        self.pack_start(box, False, False, 0)

    def _build_footer(self) -> None:
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        foot.get_style_context().add_class("panel-foot")

        self.provider_label = Gtk.Label(label="")
        self.provider_label.set_xalign(0)
        self.provider_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.provider_label.get_style_context().add_class("foot-text")
        foot.pack_start(self.provider_label, False, False, 0)

        self.effort_combo = Gtk.ComboBoxText()
        for level in config.REASONING_EFFORTS:
            self.effort_combo.append(level, level)
        self._loading_effort = True
        self.effort_combo.set_active_id(config.DEFAULT_REASONING)
        self._loading_effort = False
        self.effort_combo.set_tooltip_text("Reasoning effort sent to the model")
        self.effort_combo.get_style_context().add_class("effort-combo")
        self.effort_combo.connect("changed", self._on_effort_changed)
        foot.pack_start(self.effort_combo, False, False, 0)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.status_label.get_style_context().add_class("foot-text")
        foot.pack_start(self.status_label, True, True, 0)

        self.stop_button = Gtk.Button(label="Stop")
        self.stop_button.set_relief(Gtk.ReliefStyle.NONE)
        self.stop_button.get_style_context().add_class("foot-btn")
        self.stop_button.set_tooltip_text("Stop streaming this answer")
        self.stop_button.connect("clicked", lambda *_: self._emit(self.on_stop))
        self.stop_button.set_no_show_all(True)
        self.stop_button.set_visible(False)

        self.copy_button = Gtk.Button(label="Copy")
        self.copy_button.set_relief(Gtk.ReliefStyle.NONE)
        self.copy_button.get_style_context().add_class("foot-btn")
        self.copy_button.set_tooltip_text("Copy the last answer")
        self.copy_button.connect("clicked", lambda *_: self.copy_last())

        self.retry_button = Gtk.Button(label="Retry")
        self.retry_button.set_relief(Gtk.ReliefStyle.NONE)
        self.retry_button.get_style_context().add_class("foot-btn")
        self.retry_button.get_style_context().add_class("primary")
        self.retry_button.set_tooltip_text("Regenerate the last answer (Ctrl+Enter)")
        self.retry_button.connect("clicked", lambda *_: self._emit(self.on_retry))
        # packed right to left: Retry, then Copy, then Stop
        foot.pack_end(self.retry_button, False, False, 0)
        foot.pack_end(self.copy_button, False, False, 0)
        foot.pack_end(self.stop_button, False, False, 0)

        self.footer = foot
        self.pack_start(foot, False, False, 0)

    # ------------------------------------------------------------------ public

    def set_session(
        self,
        title: str,
        turns: list[Turn] | None = None,
        captures: list[Capture] | None = None,
        provider_label: str = "",
        web_enabled: bool = False,
    ) -> None:
        self.title_label.set_text(title or "New session")
        self.title_button.set_tooltip_text(f"{title or 'New session'} \u2014 switch session (Ctrl+S)")
        self.provider_label.set_text(provider_label)
        self.web_switch.set_active(bool(web_enabled), notify=False)
        self._turns = list(turns or [])
        self.set_captures(captures or [])
        self.clear_thread()
        self.set_active_action(None)
        for turn in self._turns:
            self._render_turn(turn)
        self.set_usage(Usage.total(self._turns))
        self._update_subline()
        self.scroll_to_bottom()

    def set_title(self, title: str) -> None:
        self.title_label.set_text(title or "New session")
        self.title_button.set_tooltip_text(f"{title or 'New session'} \u2014 switch session (Ctrl+S)")

    def set_usage(self, usage: Usage | None) -> None:
        self.usage_label.set_text(usage_text(usage))
        if usage is None or usage.is_empty:
            self.usage_label.set_tooltip_text("")
        else:
            self.usage_label.set_tooltip_text(
                f"{usage.input_tokens} input tokens, {usage.output_tokens} output tokens, "
                f"{usage.cached_tokens} of the input served from the provider cache"
            )

    def set_captures(self, captures: list[Capture]) -> None:
        self._captures = list(captures)
        for child in self._thumbs.get_children():
            self._thumbs.remove(child)
        recent = captures[-1] if captures else None
        # the header slot is 46 px wide; a wider preview would be cut off
        image = load_thumbnail(recent.path, 32, 44) if recent is not None else None
        if image is not None:
            self._thumbs.pack_start(image, False, False, 0)
        else:
            placeholder = Gtk.Label(label="no cut")
            placeholder.get_style_context().add_class("muted-label")
            self._thumbs.pack_start(placeholder, False, False, 0)
        if len(captures) > 1:
            self.thumb_count.set_text(str(len(captures)))
            self.thumb_count.set_visible(True)
        else:
            self.thumb_count.set_visible(False)
        self._thumbs.show_all()
        self._update_subline()

    def clear_thread(self) -> None:
        for child in self.thread.get_children():
            self.thread.remove(child)
        self._streaming_label = None
        self._streaming_turn = None

    def add_turn(self, turn: Turn, scroll: bool = True) -> None:
        self._turns.append(turn)
        self._render_turn(turn)
        if scroll:
            self.scroll_to_bottom()

    def _render_turn(self, turn: Turn, scroll: bool = False) -> None:
        widget = self._build_turn(turn)
        self.thread.pack_start(widget, False, False, 0)
        widget.show_all()
        self._update_subline()
        if scroll:
            self.scroll_to_bottom()

    def start_assistant_turn(self, action: str | None = None) -> Turn:
        turn = Turn(role="assistant", action=action, pending=True)
        self._streaming_turn = self._build_turn(turn)
        self._streaming_label = self._streaming_turn.label
        self._streaming_text = ""
        self._reasoning_text = ""
        self._reasoning_expander = None
        self.thread.pack_start(self._streaming_turn, False, False, 0)
        self._streaming_turn.show_all()
        self.scroll_to_bottom()
        self.set_busy(True)
        return turn

    def append_text(self, delta: str) -> None:
        if self._streaming_label is None:
            self.start_assistant_turn()
        self._streaming_text += delta
        self._streaming_label.set_markdown(self._streaming_text)
        if self._reasoning_expander is not None:
            # the answer began: fold the thinking away, it stays one click away
            self._reasoning_expander.set_expanded(False)
        self.scroll_to_bottom()

    def append_reasoning(self, delta: str) -> None:
        """Show the thinking tokens, collapsed once the answer starts."""
        if self._streaming_turn is None:
            self.start_assistant_turn()
        self._reasoning_text += delta
        expander = self._reasoning_expander
        if expander is None:
            expander = self._reasoning_block("")
            bubble = self._streaming_turn.bubble
            children = bubble.get_children()
            index = children.index(self._streaming_turn.label) if self._streaming_turn.label in children else len(children)
            bubble.pack_start(expander, False, False, 0)
            bubble.reorder_child(expander, index)
            self._reasoning_expander = expander
        expander.body.set_text(self._reasoning_text)
        expander.show()
        expander.body.show()
        # open while there is nothing else to read, like a live thinking log
        expander.set_expanded(not self._streaming_text)
        self.scroll_to_bottom()

    def finish_assistant_turn(
        self, sources: list[Source] | None = None, error: str | None = None
    ) -> None:
        if self._streaming_label is not None:
            if error:
                self._streaming_label.set_plain(error, "error-text")
            else:
                self._streaming_label.set_markdown(self._streaming_text or "\u2026")
            self._last_answer = self._streaming_text or (error or "")
        if sources and self._streaming_turn is not None:
            self._streaming_turn.add_sources(sources)
        if self._reasoning_expander is not None:
            self._reasoning_expander.set_expanded(False)
        self._streaming_label = None
        self._streaming_turn = None
        self._streaming_text = ""
        self._reasoning_text = ""
        self._reasoning_expander = None
        self.set_busy(False)
        self.scroll_to_bottom()

    def set_effort(self, value: str) -> None:
        """Select the effort without echoing it back to the app."""
        if value not in config.REASONING_EFFORTS:
            value = config.DEFAULT_REASONING
        if self.effort_combo.get_active_id() == value:
            return
        self._loading_effort = True
        self.effort_combo.set_active_id(value)
        self._loading_effort = False

    def effort_value(self) -> str:
        return self.effort_combo.get_active_id() or config.DEFAULT_REASONING

    def _on_effort_changed(self, _combo) -> None:
        if self._loading_effort:
            return
        if self.on_effort is not None:
            self.on_effort(self.effort_value())

    def set_status(self, text: str, kind: str = "info") -> None:
        styles = {"info": "", "error": "error-text", "busy": "busy-text"}
        context = self.status_label.get_style_context()
        for name in styles.values():
            if name:
                context.remove_class(name)
        if styles.get(kind):
            context.add_class(styles[kind])
        self.status_label.set_text(text)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_button.set_sensitive(not busy)
        for button in self.action_buttons.values():
            button.set_sensitive(not busy)
        self.capture_button.set_sensitive(not busy)
        self.retry_button.set_sensitive(not busy)
        self.stop_button.set_visible(busy)

    def set_active_action(self, action_id: str | None) -> None:
        self.active_action = action_id
        for identifier, button in self.action_buttons.items():
            context = button.get_style_context()
            if identifier == action_id:
                context.add_class("active")
            else:
                context.remove_class("active")

    def web_enabled(self) -> bool:
        return bool(self.web_switch.get_active())

    def set_web(self, enabled: bool) -> None:
        self.web_switch.set_active(bool(enabled), notify=False)

    def composer_text(self) -> str:
        buffer = self.composer.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, False).strip()

    def set_composer_text(self, text: str) -> None:
        self.composer.get_buffer().set_text(text)

    def clear_composer(self) -> None:
        self.set_composer_text("")

    def focus_composer(self) -> None:
        self.composer.grab_focus()

    def _composer_max_height(self) -> int:
        """Pixel height of COMPOSER_MAX_LINES lines in the composer's font."""
        layout = self.composer.create_pango_layout("Ag")
        line = layout.get_pixel_size()[1] or 15
        return line * COMPOSER_MAX_LINES + self.composer.get_top_margin() + self.composer.get_bottom_margin()

    def _on_composer_key(self, _view, event) -> bool:
        """Enter sends, Shift+Enter breaks the line (Ctrl/Cmd+Enter is Retry)."""
        if event.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        # an input method (CJK, macOS marked text) may own this Enter: it
        # confirms the composition and must not send a half-typed question
        # a generic Gdk.Event (synthesized) carries its key fields in `.key`
        if self.composer.im_context_filter_keypress(getattr(event, "key", event)):
            return True
        if event.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK | _primary_mask()):
            return False
        self._submit()
        return True

    def copy_last(self) -> None:
        text = self._last_answer.strip()
        if not text:
            self.set_status("nothing to copy")
            return
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()
        self.set_status("answer copied")

    def scroll_to_bottom(self) -> None:
        def after_layout() -> bool:
            adjustment = self.scroll.get_vadjustment()
            if adjustment is not None:
                adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            return False

        GLib.idle_add(after_layout)

    # ----------------------------------------------------------------- widgets

    def _update_subline(self) -> None:
        parts: list[str] = []
        if self._captures:
            last = self._captures[-1]
            if len(self._captures) == 1 and last.width and last.height:
                parts.append(f"{last.width} \u00d7 {last.height}")
            else:
                count = len(self._captures)
                parts.append(f"{count} capture" + ("s" if count != 1 else ""))
        else:
            parts.append("no cut")
        asks = len([turn for turn in self._turns if turn.role == "user"])
        if asks:
            parts.append(f"{asks} turn" + ("s" if asks != 1 else ""))
        if self._turns:
            parts.append("saved")
        self.sub_label.set_text(" \u00b7 ".join(parts))

    def _who_text(self, turn: Turn) -> str:
        if turn.role != "user":
            return "Assistant"
        if turn.action:
            title = dict(self._actions).get(turn.action)
            if title:
                return title
        return "Follow-up"

    def _build_turn(self, turn: Turn) -> Gtk.Box:
        frame = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        avatar = Gtk.Label(label="Y" if turn.role == "user" else "C")
        avatar.set_size_request(17, 17)
        avatar.set_xalign(0.5)
        avatar.set_yalign(0.5)
        avatar.set_valign(Gtk.Align.START)
        avatar.get_style_context().add_class("avatar")
        avatar.get_style_context().add_class(
            "avatar-user" if turn.role == "user" else "avatar-ai"
        )
        frame.pack_start(avatar, False, False, 0)

        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        who = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tag = Gtk.Label(label=self._who_text(turn).upper())
        tag.set_xalign(0)
        tag.get_style_context().add_class("who")
        if turn.role == "user" and turn.action:
            tag.get_style_context().add_class(f"who-{turn.action}")
        who.pack_start(tag, False, False, 0)
        stamp = Gtk.Label(label=clock(turn.created_at))
        stamp.set_xalign(1)
        stamp.set_hexpand(True)
        stamp.get_style_context().add_class("tstamp")
        who.pack_end(stamp, False, False, 0)
        bubble.pack_start(who, False, False, 0)

        if turn.captures:
            bubble.pack_start(self._crop_row(turn.captures), False, False, 0)

        if turn.reasoning:
            bubble.pack_start(self._reasoning_block(turn.reasoning), False, False, 0)

        label = MarkdownView(on_link=self._on_source_link)
        if turn.text:
            label.set_markdown(turn.text)
        else:
            label.set_plain("\u2026")
        bubble.pack_start(label, False, False, 0)

        if turn.sources:
            bubble.pack_start(self._sources_block(turn.sources), False, False, 0)

        frame.pack_start(bubble, True, True, 0)
        frame.label = label
        frame.bubble = bubble

        def add_sources(sources: list[Source], frame=frame) -> None:
            frame.bubble.pack_start(self._sources_block(sources), False, False, 0)
            frame.bubble.show_all()

        frame.add_sources = add_sources
        return frame

    def _reasoning_block(self, text: str) -> Gtk.Expander:
        """Collapsed thinking log, like the one llama.cpp draws.

        It opens while the model is still thinking and folds away as soon as the
        answer starts, so the reply stays readable but the tokens are one click
        away.
        """
        expander = Gtk.Expander()
        expander.set_expanded(False)
        expander.get_style_context().add_class("reasoning-block")
        head = Gtk.Label()
        head.set_use_markup(True)
        head.set_markup('<span size="small">REASONING</span>')
        head.set_xalign(0)
        expander.set_label_widget(head)
        body = Gtk.Label(label=text)
        body.set_line_wrap(True)
        body.set_xalign(0)
        body.set_selectable(True)
        body.set_margin_top(3)
        body.set_margin_bottom(3)
        body.get_style_context().add_class("reasoning-body")
        expander.add(body)
        expander.body = body
        return expander

    def _crop_row(self, capture_ids: list[str]) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=CROP_SPACING)
        row.set_margin_top(2)
        row.set_margin_bottom(2)
        captures = [
            capture
            for capture_id in capture_ids[-3:]
            for capture in self._captures
            if capture.id == capture_id
        ]
        # share the row so even three wide cuts never push the panel wider
        max_width = (CROP_ROW_WIDTH - CROP_SPACING * max(0, len(captures) - 1)) // max(
            1, len(captures)
        )
        for capture in captures:
            row.pack_start(self._crop_mini(capture, max_width), False, False, 0)
        return row

    def _crop_mini(self, capture: Capture, max_width: int = CROP_ROW_WIDTH) -> Gtk.Widget:
        overlay = Gtk.Overlay()
        image = load_image(capture.path, CROP_HEIGHT, max_width)
        if image is None:
            overlay.set_size_request(min(88, max_width), CROP_HEIGHT)
        if image is not None:
            image.get_style_context().add_class("crop-mini")
            overlay.add(image)
        if capture.width and capture.height:
            size = Gtk.Label(label=f"{capture.width} \u00d7 {capture.height}")
            size.get_style_context().add_class("crop-size")
            size.set_halign(Gtk.Align.START)
            size.set_valign(Gtk.Align.END)
            size.set_margin_start(3)
            size.set_margin_bottom(2)
            overlay.add_overlay(size)
        return overlay

    def _sources_block(self, sources: list[Source]) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(5)
        head = Gtk.Label(label=f"SOURCES \u00b7 {len(sources)}")
        head.set_xalign(0)
        head.get_style_context().add_class("sources-head")
        box.pack_start(head, False, False, 0)
        for index, source in enumerate(sources, start=1):
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_line_wrap(True)
            label.set_selectable(True)
            label.set_markup(source_markup(index, source))
            label.get_style_context().add_class("source-label")
            if source.url:
                label.set_tooltip_text(f"Open {source.url}")
                label.connect("activate-link", self._on_source_link)
            box.pack_start(label, False, False, 0)
        return box

    def _on_source_link(self, _label: Gtk.Label, uri: str) -> bool:
        """Open the cited page in the user's browser; never let GTK guess."""
        if not uri.startswith(("http://", "https://")):
            return True
        toplevel = self.get_toplevel()
        window = toplevel if isinstance(toplevel, Gtk.Window) else None
        try:
            Gtk.show_uri_on_window(window, uri, Gtk.get_current_event_time())
        except GLib.Error as exc:  # pragma: no cover - no handler installed
            self.set_status(f"cannot open the link: {exc.message}", "error")
        return True

    # ------------------------------------------------------------------ events

    def _emit(self, callback: Callable | None, *args) -> None:
        if callback is not None:
            callback(*args)

    def _on_action(self, _button, action_id: str) -> None:
        self.set_active_action(action_id)
        if self.on_prompt is not None:
            self.on_prompt(action_id, action_id)

    def _on_web_change(self, active: bool) -> None:
        if self.on_web is not None:
            self.on_web(active)

    def _sync_ask_state(self) -> None:
        """Highlight the box once it holds text or has the focus, like the wireframe."""
        context = self.ask_box.get_style_context()
        buffer = self.composer.get_buffer()
        self.placeholder.set_visible(buffer.get_char_count() == 0)
        if self.composer_text():
            context.add_class("filled")
        else:
            context.remove_class("filled")
        if self.composer.has_focus():
            context.add_class("ask-focus")
        else:
            context.remove_class("ask-focus")

    def _submit(self) -> None:
        if self._busy:
            return
        text = self.composer_text()
        if not text or self.on_send is None:
            return
        self.clear_composer()
        self.on_send(text)


def _primary_mask() -> Gdk.ModifierType:
    """Command on macOS, Control elsewhere; the panel accepts both."""
    display = Gdk.Display.get_default()
    if display is None:
        return Gdk.ModifierType.CONTROL_MASK
    keymap = Gdk.Keymap.get_for_display(display)
    return keymap.get_modifier_mask(Gdk.ModifierIntent.PRIMARY_ACCELERATOR)


class PanelWindow(Gtk.Window):
    """Frameless always on top window that hosts the panel."""

    def __init__(self, **kwargs) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        theme.apply_css()
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_above(True)
        # the portal only shows its access dialog when the calling app holds focus
        self.set_accept_focus(True)
        self.set_focus_on_map(True)
        self.set_wmclass("chinchilla", "Chinchilla")
        self.set_default_size(PANEL_WIDTH, 640)
        self.content = PanelContent(**kwargs)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.get_style_context().add_class("panel-frame")
        frame.pack_start(self.content, True, True, 0)
        self.add(frame)
        self.connect("key-press-event", self._on_key)
        # Drag from the header itself: the title button must stay clickable for
        # the session selector, so it is not a drag handle.
        self.content.header.connect("button-press-event", self._start_drag)
        self.connect("delete-event", self._on_delete)

    def _on_delete(self, *_args) -> bool:
        self.hide()
        return True

    def _start_drag(self, _widget, event) -> bool:
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return False

    def _typing(self) -> bool:
        """True when the composer has the focus, so digits are text, not shortcuts."""
        focused = self.get_focus()
        return isinstance(focused, (Gtk.Entry, Gtk.TextView))

    def _on_key(self, _widget, event) -> bool:
        ctrl = bool(event.state & (Gdk.ModifierType.CONTROL_MASK | _primary_mask()))
        content = self.content
        if self._escape(event):
            return True
        if not ctrl and not self._typing() and event.keyval in (
            Gdk.KEY_1,
            Gdk.KEY_2,
            Gdk.KEY_3,
        ):
            index = event.keyval - Gdk.KEY_1
            if 0 <= index < len(content._actions):
                action_id = content._actions[index][0]
                content.action_buttons[action_id].clicked()
                return True
        if ctrl and event.keyval in (Gdk.KEY_r,):
            if content.on_capture:
                content.on_capture()
            return True
        if ctrl and event.keyval == Gdk.KEY_n:
            if content.on_new_session:
                content.on_new_session()
            return True
        if ctrl and event.keyval == Gdk.KEY_s:
            if content.on_sessions:
                content.on_sessions()
            return True
        if ctrl and event.keyval == Gdk.KEY_w:
            content.web_switch.set_active(not content.web_switch.get_active())
            return True
        if ctrl and event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if content.on_retry:
                content.on_retry()
            return True
        return False

    def _escape(self, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def place(self, screen_width: int, screen_height: int, margin: int = 24) -> None:
        height = int(screen_height * 0.72)
        self.resize(PANEL_WIDTH, height)
        self.move(
            max(0, screen_width - PANEL_WIDTH - margin),
            max(0, (screen_height - height) // 2),
        )

    def parent_handle(self) -> str:
        """X11 handle for the portal, so it can attach its dialog to the panel."""
        window = self.get_window()
        if window is None:
            return ""
        try:
            xid = window.get_xid()
        except (AttributeError, TypeError):
            # Wayland toplevels have no X11 handle to hand to the portal
            return ""
        return f"x11:{xid:#x}" if xid else ""

    def show_at(self, screen_width: int, screen_height: int) -> None:
        self.place(screen_width, screen_height)
        self.show_all()
        self.present_with_time(Gdk.CURRENT_TIME)
        if system.is_mac():
            from ..macos import cocoa

            cocoa.keep_visible(self)
        self.grab_focus()


def _demo_capture() -> Path:
    """Small synthetic capture so renders do not depend on the desktop."""
    import tempfile

    from PIL import Image, ImageDraw

    path = Path(tempfile.gettempdir()) / "chinchilla-demo-capture.png"
    if not path.exists():
        image = Image.new("RGB", (260, 150), (248, 248, 244))
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, 260, 22], fill=(226, 88, 72))
        draw.text((8, 6), "Connection error", fill=(255, 255, 255))
        draw.rectangle([12, 40, 244, 46], fill=(210, 210, 206))
        draw.rectangle([12, 60, 200, 66], fill=(210, 210, 206))
        draw.rectangle([12, 96, 104, 126], fill=(230, 175, 60))
        image.save(path)
    return path


def demo_content(width: int = PANEL_WIDTH, height: int = 760) -> PanelContent:
    """Panel filled with sample data, used for rendering checks."""
    theme.apply_css()
    content = PanelContent()
    capture = Capture(path=str(_demo_capture()), width=620, height=214)
    other = Capture(path=str(_demo_capture()), width=410, height=180)
    content.set_session(
        title="Q3 invoice \u2014 revenue note",
        turns=[
            Turn(role="user", text="Translate", captures=[capture.id], action="translate"),
            Turn(
                role="assistant",
                text="The quarterly report shows a **12% increase in revenue** during the "
                "third quarter, driven mainly by the new subscription plan.",
                usage=Usage(1200, 240, 900),
            ),
            Turn(
                role="user",
                text="What is the main risk mentioned here? Compare it with the chart "
                "I just added.",
                captures=[capture.id, other.id],
            ),
            Turn(
                role="assistant",
                text="The text flags one explicit risk: the 12% growth depends on a single "
                "subscription tier still in its discounted introductory period.\n\n"
                "The chart agrees \u2014 the amber series flattens right after the promo "
                "window, so the run-rate does not hold without new sign-ups.",
                reasoning="The user asks about risk. The text names the promo window, the "
                "chart shows the amber series flattening after it, so the two agree.",
                sources=[Source(title="Handling expired tokens", url="https://example.com/tokens")],
                usage=Usage(2400, 320, 1800),
            ),
        ],
        captures=[capture, other],
        provider_label="anthropic \u00b7 claude-sonnet-4",
        web_enabled=True,
    )
    content.set_status("ready \u00b7 2 cuts \u00b7 web on")
    content.set_size_request(width, height)
    return content
