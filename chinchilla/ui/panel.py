"""The response panel: session header, quick actions, thread and composer."""

from __future__ import annotations

import html
import re
import time
from pathlib import Path
from typing import Callable

from ..core.thread import Capture, Source, Turn
from . import theme
from .gtk import Gdk, GdkPixbuf, GLib, Gtk

PANEL_WIDTH = 404
PADDING = 12

DEFAULT_ACTIONS = [
    ("translate", "Translate"),
    ("explain", "Explain"),
    ("grammar", "Fix grammar"),
]

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def to_pango(text: str) -> str:
    """Very small markdown subset -> pango markup, always escaped first."""
    escaped = html.escape(text or "")
    escaped = _CODE.sub(r"<tt>\1</tt>", escaped)
    escaped = _BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC.sub(r"<i>\1</i>", escaped)
    lines = []
    for line in escaped.splitlines():
        if line.startswith("- "):
            line = "  \u2022 " + line[2:]
        lines.append(line)
    return "\n".join(lines)


def clock(timestamp: float) -> str:
    return time.strftime("%H:%M", time.localtime(timestamp))


def load_thumbnail(path: str, size: int = 40) -> Gtk.Widget | None:
    """Small preview of a capture, used in the header and the thread."""
    if not path or not Path(path).is_file():
        return None
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    except Exception:
        return None
    width = max(1, int(pixbuf.get_width() * size / max(1, pixbuf.get_height())))
    scaled = pixbuf.scale_simple(width, size, GdkPixbuf.InterpType.BILINEAR)
    image = Gtk.Image.new_from_pixbuf(scaled)
    image.get_style_context().add_class("thumb")
    return image


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

        self._actions = list(actions or DEFAULT_ACTIONS)
        self._captures: list[Capture] = []
        self._busy = False
        self._streaming_label: Gtk.Label | None = None
        self._streaming_text = ""
        self._streaming_turn: Gtk.Box | None = None

        self._build_header()
        self._build_tools()
        self._build_actions()
        self._build_thread()
        self._build_composer()
        self._build_status()

    # ------------------------------------------------------------------ build

    def _build_header(self) -> None:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.set_margin_start(PADDING)
        header.set_margin_end(PADDING)
        header.set_margin_top(10)
        header.set_margin_bottom(6)

        self.thumb_stack = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.thumb_stack.set_size_request(34, 34)
        self.thumb_stack.set_valign(Gtk.Align.CENTER)
        header.pack_start(self.thumb_stack, False, False, 0)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.title_button = Gtk.Button()
        self.title_button.set_relief(Gtk.ReliefStyle.NONE)
        self.title_button.get_style_context().add_class("session-title")
        self.title_label = Gtk.Label(label="New session")
        self.title_label.set_xalign(0)
        self.title_label.set_halign(Gtk.Align.START)
        self.title_label.set_ellipsize(3)
        self.title_label.set_max_width_chars(20)
        self.title_button.add(self.title_label)
        self.title_button.set_tooltip_text("Switch session (Ctrl+S)")
        self.title_button.set_halign(Gtk.Align.START)
        self.title_button.connect("clicked", lambda *_: self._emit(self.on_sessions))
        titles.pack_start(self.title_button, False, False, 0)

        self.provider_label = Gtk.Label(label="")
        self.provider_label.set_xalign(0)
        self.provider_label.get_style_context().add_class("muted-label")
        titles.pack_start(self.provider_label, False, False, 0)
        header.pack_start(titles, True, True, 0)

        settings_button = Gtk.Button(label="\u2699")
        settings_button.set_relief(Gtk.ReliefStyle.NONE)
        settings_button.set_tooltip_text("Settings")
        settings_button.connect("clicked", lambda *_: self._emit(self.on_settings))
        header.pack_end(settings_button, False, False, 0)

        close = Gtk.Button(label="\u00d7")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Hide (Ctrl+H)")
        close.connect("clicked", lambda *_: self._emit(self.on_close))
        header.pack_end(close, False, False, 0)

        self.pack_start(header, False, False, 0)

    def _build_tools(self) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_start(PADDING)
        row.set_margin_end(PADDING)
        row.set_margin_bottom(8)

        self.web_switch = Gtk.Switch()
        self.web_switch.set_valign(Gtk.Align.CENTER)
        self.web_switch.set_tooltip_text("Let the agent search the web (Ctrl+W)")
        self.web_switch.connect("notify::active", self._on_web_switch)
        web_label = Gtk.Label(label="Web")
        web_label.get_style_context().add_class("muted-label")
        row.pack_start(self.web_switch, False, False, 0)
        row.pack_start(web_label, False, False, 0)

        spacer = Gtk.Box()
        row.pack_start(spacer, True, True, 0)

        self.capture_button = Gtk.Button(label="+ Capture")
        self.capture_button.get_style_context().add_class("ghost-button")
        self.capture_button.set_tooltip_text("Add another screen cut (Ctrl+R)")
        self.capture_button.connect("clicked", lambda *_: self._emit(self.on_capture))
        row.pack_end(self.capture_button, False, False, 0)

        self.new_button = Gtk.Button(label="+ New session")
        self.new_button.get_style_context().add_class("ghost-button")
        self.new_button.connect("clicked", lambda *_: self._emit(self.on_new_session))
        row.pack_end(self.new_button, False, False, 0)

        self.pack_start(row, False, False, 0)

    def _build_actions(self) -> None:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_start(PADDING)
        row.set_margin_end(PADDING)
        row.set_margin_bottom(8)
        self.action_buttons: dict[str, Gtk.Button] = {}
        for action_id, title in self._actions:
            button = Gtk.Button(label=title)
            button.get_style_context().add_class("pill")
            button.set_tooltip_text(f"Send the {title} prompt")
            button.connect("clicked", self._on_action, action_id)
            row.pack_start(button, True, True, 0)
            self.action_buttons[action_id] = button
        self.pack_start(row, False, False, 0)

    def _build_thread(self) -> None:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_margin_start(PADDING)
        scroll.set_margin_end(PADDING)
        scroll.set_overlay_scrolling(True)
        self.thread = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.thread.set_valign(Gtk.Align.START)
        scroll.add(self.thread)
        scroll.set_size_request(-1, 220)
        self.scroll = scroll
        self.pack_start(scroll, True, True, 0)

    def _build_composer(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_start(PADDING)
        box.set_margin_end(PADDING)
        box.set_margin_top(8)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 52)
        self.entry = Gtk.TextView()
        self.entry.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.entry.get_style_context().add_class("composer")
        self.entry.set_left_margin(6)
        self.entry.set_right_margin(6)
        self.entry.connect("key-press-event", self._on_entry_key)
        scroll.add(self.entry)
        box.pack_start(scroll, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.hint_label = Gtk.Label(label="Enter to send, Shift+Enter for a new line")
        self.hint_label.set_xalign(0)
        self.hint_label.get_style_context().add_class("muted-label")
        row.pack_start(self.hint_label, True, True, 0)
        self.send_button = Gtk.Button(label="Send")
        self.send_button.get_style_context().add_class("accent-button")
        self.send_button.connect("clicked", lambda *_: self._submit())
        row.pack_end(self.send_button, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.pack_start(box, False, False, 0)

    def _build_status(self) -> None:
        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)
        self.status_label.get_style_context().add_class("muted-label")
        self.status_label.set_margin_start(PADDING)
        self.status_label.set_margin_end(PADDING)
        self.status_label.set_margin_top(6)
        self.status_label.set_margin_bottom(8)
        self.status_label.set_ellipsize(3)
        self.pack_start(self.status_label, False, False, 0)

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
        self.title_label.set_tooltip_text(title or "New session")
        self.provider_label.set_text(provider_label)
        self.web_switch.set_active(bool(web_enabled))
        self.set_captures(captures or [])
        self.clear_thread()
        for turn in turns or []:
            self.add_turn(turn, scroll=False)
        self.scroll_to_bottom()

    def set_title(self, title: str) -> None:
        self.title_label.set_text(title or "New session")
        self.title_label.set_tooltip_text(title or "New session")

    def set_captures(self, captures: list[Capture]) -> None:
        self._captures = list(captures)
        for child in self.thumb_stack.get_children():
            self.thumb_stack.remove(child)
        if not captures:
            placeholder = Gtk.Label(label="no cut")
            placeholder.get_style_context().add_class("muted-label")
            self.thumb_stack.pack_start(placeholder, False, False, 0)
        else:
            for capture in captures[-2:]:
                thumb = load_thumbnail(capture.path, 32)
                if thumb is not None:
                    self.thumb_stack.pack_start(thumb, False, False, 0)
            if len(captures) > 2:
                more = Gtk.Label(label=f"+{len(captures) - 2}")
                more.get_style_context().add_class("muted-label")
                self.thumb_stack.pack_start(more, False, False, 0)
        self.thumb_stack.show_all()

    def clear_thread(self) -> None:
        for child in self.thread.get_children():
            self.thread.remove(child)
        self._streaming_label = None
        self._streaming_turn = None

    def add_turn(self, turn: Turn, scroll: bool = True) -> None:
        if turn.role == "user":
            widget = self._build_user_turn(turn)
        else:
            widget = self._build_assistant_turn(turn)
        self.thread.pack_start(widget, False, False, 0)
        widget.show_all()
        if scroll:
            self.scroll_to_bottom()

    def start_assistant_turn(self, action: str | None = None) -> Turn:
        turn = Turn(role="assistant", action=action, pending=True)
        self._streaming_turn = self._build_assistant_turn(turn)
        self._streaming_label = self._streaming_turn.label
        self._streaming_text = ""
        self.thread.pack_start(self._streaming_turn, False, False, 0)
        self._streaming_turn.show_all()
        self.scroll_to_bottom()
        self.set_busy(True)
        return turn

    def append_text(self, delta: str) -> None:
        if self._streaming_label is None:
            self.start_assistant_turn()
        self._streaming_text += delta
        self._streaming_label.set_markup(to_pango(self._streaming_text))
        self.scroll_to_bottom()

    def finish_assistant_turn(self, sources: list[Source] | None = None, error: str | None = None) -> None:
        if self._streaming_label is not None:
            text = error or self._streaming_text or "\u2026"
            if error:
                self._streaming_label.get_style_context().add_class("error-text")
            self._streaming_label.set_markup(to_pango(text))
        if sources and self._streaming_turn is not None:
            self._streaming_turn.add_sources(sources)
        self._streaming_label = None
        self._streaming_turn = None
        self._streaming_text = ""
        self.set_busy(False)
        self.scroll_to_bottom()

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

    def web_enabled(self) -> bool:
        return bool(self.web_switch.get_active())

    def composer_text(self) -> str:
        buffer = self.entry.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()

    def clear_composer(self) -> None:
        self.entry.get_buffer().set_text("")

    def focus_composer(self) -> None:
        self.entry.grab_focus()

    def scroll_to_bottom(self) -> None:
        def after_layout() -> bool:
            adjustment = self.scroll.get_vadjustment()
            if adjustment is not None:
                adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            return False

        GLib.idle_add(after_layout)

    # ----------------------------------------------------------------- widgets

    def _build_user_turn(self, turn: Turn) -> Gtk.Box:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        frame.set_halign(Gtk.Align.END)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bubble.get_style_context().add_class("user-card")
        bubble.set_margin_start(24)

        text = turn.text or "Screen cut"
        label = Gtk.Label()
        label.set_markup(to_pango(text))
        label.set_line_wrap(True)
        label.set_xalign(0)
        label.get_style_context().add_class("body-label")
        bubble.pack_start(label, False, False, 0)

        if turn.captures:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            for capture_id in turn.captures[-3:]:
                capture = next((c for c in self._captures if c.id == capture_id), None)
                if capture is None:
                    continue
                thumb = load_thumbnail(capture.path, 44)
                if thumb is not None:
                    row.pack_start(thumb, False, False, 0)
            bubble.pack_start(row, False, False, 0)

        frame.pack_start(bubble, False, False, 0)
        stamp = Gtk.Label(label=clock(turn.created_at))
        stamp.set_xalign(1)
        stamp.get_style_context().add_class("muted-label")
        frame.pack_start(stamp, False, False, 0)
        return frame

    def _build_assistant_turn(self, turn: Turn) -> Gtk.Box:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        frame.set_halign(Gtk.Align.START)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bubble.get_style_context().add_class("card")
        bubble.set_margin_end(12)

        label = Gtk.Label()
        label.set_line_wrap(True)
        label.set_xalign(0)
        label.set_selectable(True)
        label.get_style_context().add_class("body-label")
        if turn.text:
            label.set_markup(to_pango(turn.text))
        else:
            label.set_text("\u2026")
        bubble.pack_start(label, False, False, 0)

        if turn.sources:
            bubble.pack_start(self._sources_block(turn.sources), False, False, 0)

        frame.pack_start(bubble, False, False, 0)
        frame.label = label
        frame.bubble = bubble

        def add_sources(sources: list[Source], frame=frame) -> None:
            frame.bubble.pack_start(self._sources_block(sources), False, False, 0)
            frame.bubble.show_all()

        frame.add_sources = add_sources
        return frame

    def _sources_block(self, sources: list[Source]) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(2)
        title = Gtk.Label(label="Sources")
        title.set_xalign(0)
        title.get_style_context().add_class("muted-label")
        box.pack_start(title, False, False, 0)
        for index, source in enumerate(sources, start=1):
            label = Gtk.Label()
            label.set_xalign(0)
            label.set_line_wrap(True)
            label.set_markup(f"{index}. {html.escape(source.title or source.url)}")
            label.get_style_context().add_class("source-label")
            if source.url:
                label.set_tooltip_text(source.url)
            box.pack_start(label, False, False, 0)
        return box

    # ------------------------------------------------------------------ events

    def _emit(self, callback: Callable | None, *args) -> None:
        if callback is not None:
            callback(*args)

    def _on_action(self, _button, action_id: str) -> None:
        if self.on_prompt is not None:
            self.on_prompt(action_id, action_id)

    def _on_web_switch(self, switch, _param) -> None:
        if self.on_web is not None:
            self.on_web(bool(switch.get_active()))

    def _on_entry_key(self, _widget, event) -> bool:
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if event.state & Gdk.ModifierType.SHIFT_MASK:
                return False
            self._submit()
            return True
        return False

    def _submit(self) -> None:
        if self._busy:
            return
        text = self.composer_text()
        if not text or self.on_send is None:
            return
        self.clear_composer()
        self.on_send(text)


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
        self.set_wmclass("chinchilla", "Chinchilla")
        self.set_default_size(PANEL_WIDTH, 640)
        self.content = PanelContent(**kwargs)
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.get_style_context().add_class("panel-frame")
        frame.pack_start(self.content, True, True, 0)
        self.add(frame)
        self.connect("key-press-event", self._on_key)
        self.content.title_button.connect("button-press-event", self._start_drag)
        self.connect("delete-event", self._on_delete)

    def _on_delete(self, *_args) -> bool:
        self.hide()
        return True

    def _start_drag(self, _widget, event) -> bool:
        if event.button == 1:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root), event.time)
        return False

    def _on_key(self, _widget, event) -> bool:
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        content = self.content
        if self._escape(event):
            return True
        if ctrl and event.keyval == Gdk.KEY_r:
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
        return False

    def _escape(self, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide()
            return True
        return False

    def place(self, screen_width: int, screen_height: int, margin: int = 24) -> None:
        height = int(screen_height * 0.72)
        self.resize(PANEL_WIDTH, height)
        self.move(max(0, screen_width - PANEL_WIDTH - margin), max(0, (screen_height - height) // 2))

    def show_at(self, screen_width: int, screen_height: int) -> None:
        self.place(screen_width, screen_height)
        self.show_all()
        self.present()


def _demo_capture() -> Path:
    """Small synthetic capture so renders show real thumbnails."""
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
    capture = Capture(path=str(_demo_capture()), width=520, height=300)
    content.set_session(
        title="Translate a dashboard error",
        turns=[
            Turn(role="user", text="Translate", captures=[capture.id], action="translate"),
            Turn(
                role="assistant",
                text="**Error de conexion**\n\nNo se pudo conectar con el servidor. "
                "Revisa tu red e intentalo de nuevo.",
            ),
            Turn(role="user", text="Explain why this fails on the second attempt"),
            Turn(
                role="assistant",
                text="The retry reuses an expired token, so the second call is "
                "rejected. `retry_after` should reset the session first.\n\n"
                "- Token expires after 60 s\n- Retries keep the old header",
                sources=[Source(title="Handling expired tokens", url="https://example.com/tokens")],
            ),
        ],
        captures=[capture],
        provider_label="custom \u00b7 deepseek-v4.1-flash",
        web_enabled=True,
    )
    content.set_status("ready \u00b7 2 cuts \u00b7 web on")
    content.set_size_request(width, height)
    return content
