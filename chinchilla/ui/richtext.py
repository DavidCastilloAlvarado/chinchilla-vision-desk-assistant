"""A markdown answer as GTK widgets: prose labels plus boxed code and tables."""

from __future__ import annotations

import html
from typing import Callable

from . import markdown
from .gtk import GLib, Gtk, Pango

COPIED_MS = 1200


class CodeBlock(Gtk.Box):
    """Monospace box with the language and a Copy button, like a chat app."""

    def __init__(self, block: markdown.Block) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.kind = block.kind
        self.code = ""
        self.get_style_context().add_class("code-block")

        self.head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.lang_label = Gtk.Label(label="")
        self.lang_label.set_xalign(0)
        self.lang_label.get_style_context().add_class("code-lang")
        self.head.pack_start(self.lang_label, True, True, 0)
        self.copy_button = Gtk.Button(label="Copy")
        self.copy_button.set_relief(Gtk.ReliefStyle.NONE)
        self.copy_button.get_style_context().add_class("code-copy")
        self.copy_button.connect("clicked", lambda *_: self.copy())
        self.head.pack_end(self.copy_button, False, False, 0)
        self.pack_start(self.head, False, False, 0)

        self.body = Gtk.Label(label="")
        self.body.set_xalign(0)
        self.body.set_selectable(True)
        self.body.set_line_wrap(True)
        # long SQL or shell lines break anywhere instead of widening the panel
        self.body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.body.get_style_context().add_class("code-text")
        self.pack_start(self.body, False, False, 0)
        self.update(block)

    def update(self, block: markdown.Block) -> None:
        self.lang_label.set_text(block.lang or ("table" if block.kind == "table" else "code"))
        if block.body != self.code:
            self.code = block.body
            self.body.set_text(block.body)

    def copy(self) -> None:
        clipboard = Gtk.Clipboard.get_default(self.get_display())
        clipboard.set_text(self.code, -1)
        clipboard.store()
        self.copy_button.set_label("Copied")
        GLib.timeout_add(COPIED_MS, self._reset_copy)

    def _reset_copy(self) -> bool:
        self.copy_button.set_label("Copy")
        return False


class MarkdownView(Gtk.Box):
    """Rebuilds only when the block layout changes, so streaming stays cheap."""

    def __init__(self, on_link: Callable[[Gtk.Label, str], bool] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.on_link = on_link
        self.text = ""
        self._shape: list[str] = []
        # body each prose label shows, so a stream only re-renders the block
        # that is still growing
        self._bodies: list[str] = []

    def _prose_label(self) -> Gtk.Label:
        label = Gtk.Label()
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_xalign(0)
        label.set_selectable(True)
        label.get_style_context().add_class("turn-body")
        if self.on_link is not None:
            label.connect("activate-link", self.on_link)
        return label

    def _clear(self) -> None:
        for child in self.get_children():
            self.remove(child)
            child.destroy()
        self._shape = []
        self._bodies = []

    def set_markdown(self, text: str) -> None:
        self.text = text or ""
        blocks = markdown.parse_blocks(self.text) or [markdown.Block("text", "\u2026")]
        shape = [block.kind for block in blocks]
        if shape != self._shape:
            self._clear()
            for block in blocks:
                widget = self._prose_label() if block.kind == "text" else CodeBlock(block)
                self.pack_start(widget, False, False, 0)
            self._shape = shape
            self._bodies = [None] * len(blocks)
        for index, (widget, block) in enumerate(zip(self.get_children(), blocks)):
            if self._bodies[index] == block.body:
                continue
            if block.kind == "text":
                widget.set_markup(markdown.prose_markup(block.body))
            else:
                widget.update(block)
            self._bodies[index] = block.body
        self.show_all()

    def set_plain(self, text: str, css_class: str | None = None) -> None:
        """Unformatted text, for errors and placeholders."""
        self.text = markdown.clean(text)
        self._clear()
        label = self._prose_label()
        label.set_markup(html.escape(self.text, quote=False))
        if css_class:
            label.get_style_context().add_class(css_class)
        self.pack_start(label, False, False, 0)
        self._shape = ["plain"]
        self.show_all()
