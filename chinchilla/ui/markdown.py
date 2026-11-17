"""Markdown from the model, turned into what GTK can show.

Answers mix prose with fenced code (SQL, shell, JSON). A `Gtk.Label` takes
Pango markup, which has no notion of blocks, so the text is split into
blocks first: prose becomes markup for a label, code and tables become their
own monospace boxes. Nothing from the model reaches Pango unescaped, and a
block whose markup Pango would refuse falls back to plain text instead of
leaving the bubble empty.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

CODE_INLINE = '<span font_family="monospace" background="#232a36" foreground="#e6edf3">{}</span>'
QUOTE_COLOR = "#8b95a7"
RULE = '<span foreground="#3a4354">' + "\u2500" * 24 + "</span>"

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})([^`]*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
# trailing `#`s are trimmed in Python: a lazy body before `\s*#*\s*$`
# backtracked cubically on long runs of spaces
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_HR = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")

_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_ITALIC = re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![*\w])|(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_TOKEN = re.compile("\x00(\\d+)\x00")
_LINK_TAG = re.compile(r"<a href=\"[^\"]*\">|</a>")


def clean(text: str | None) -> str:
    """Model text as GTK can take it.

    A NUL cuts a GTK string short and collides with the placeholders used
    below, so it is dropped before anything else sees it.
    """
    return (text or "").replace("\x00", "").replace("\r\n", "\n")


@dataclass
class Block:
    kind: str  # "text", "code" or "table"
    body: str
    lang: str = ""


def parse_blocks(text: str) -> list[Block]:
    """Split markdown into prose, fenced code and pipe tables.

    An unterminated fence runs to the end, so a streaming answer shows its
    code as code before the closing fence arrives.
    """
    blocks: list[Block] = []
    prose: list[str] = []
    lines = clean(text).split("\n")

    def flush() -> None:
        body = "\n".join(prose).strip("\n")
        if body.strip():
            blocks.append(Block("text", body))
        prose.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker = fence.group(1)
            info = fence.group(2).strip().split()
            lang = info[0].lower() if info else ""
            code: list[str] = []
            index += 1
            while index < len(lines):
                closing = lines[index].strip()
                if closing.startswith(marker[0] * len(marker)) and not closing.strip(marker[0]):
                    break
                code.append(lines[index])
                index += 1
            blocks.append(Block("code", "\n".join(code), lang))
            index += 1
            continue
        if _TABLE_ROW.match(line) and index + 1 < len(lines) and _TABLE_RULE.match(lines[index + 1]):
            flush()
            rows = [line]
            index += 1
            while index < len(lines) and _TABLE_ROW.match(lines[index]):
                rows.append(lines[index])
                index += 1
            blocks.append(Block("table", format_table(rows)))
            continue
        prose.append(line)
        index += 1
    flush()
    return blocks


def format_table(rows: list[str]) -> str:
    """Pipe table to aligned monospace columns, without the |---| rule."""
    cells = [
        [cell.strip() for cell in row.strip().strip("|").split("|")]
        for row in rows
        if not _TABLE_RULE.match(row)
    ]
    if not cells:
        return ""
    count = max(len(row) for row in cells)
    for row in cells:
        row.extend([""] * (count - len(row)))
    widths = [max(len(row[column]) for row in cells) for column in range(count)]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in cells]
    lines.insert(1, "  ".join("\u2500" * width for width in widths))
    return "\n".join(lines)


def inline_markup(text: str) -> str:
    """Inline markdown of one line, escaped, as Pango markup."""
    tokens: list[str] = []

    def keep(markup: str) -> str:
        tokens.append(markup)
        return f"\x00{len(tokens) - 1}\x00"

    # code first: nothing inside backticks is formatting
    text = _CODE_SPAN.sub(lambda m: keep(CODE_INLINE.format(html.escape(m.group(2).strip()))), text)
    text = _LINK.sub(
        lambda m: keep(
            f'<a href="{html.escape(m.group(2), quote=True)}">{html.escape(m.group(1))}</a>'
        ),
        text,
    )
    text = html.escape(text, quote=False)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)

    def restore(match: re.Match) -> str:
        index = int(match.group(1))
        return tokens[index] if index < len(tokens) else ""

    # a token can hold another one (a link whose text is `code`)
    for _ in range(len(tokens) + 1):
        if not _TOKEN.search(text):
            break
        text = _TOKEN.sub(restore, text)
    return text


def _line_markup(line: str) -> str:
    heading = _HEADING.match(line)
    if heading:
        size = "large" if len(heading.group(1)) == 1 else "medium"
        return f'<span size="{size}" weight="bold">{inline_markup(_heading_text(heading.group(2)))}</span>'
    if _HR.match(line):
        return RULE
    bullet = _BULLET.match(line)
    if bullet:
        depth = len(bullet.group(1).expandtabs(2)) // 2
        mark = "\u2022" if depth % 2 == 0 else "\u25e6"
        return "  " * (depth + 1) + f"{mark} " + inline_markup(bullet.group(2))
    numbered = _NUMBERED.match(line)
    if numbered:
        depth = len(numbered.group(1).expandtabs(2)) // 2
        return "  " * (depth + 1) + f"{numbered.group(2)}. " + inline_markup(numbered.group(3))
    quote = _QUOTE.match(line)
    if quote:
        return f'<span foreground="{QUOTE_COLOR}">\u2502 {inline_markup(quote.group(1))}</span>'
    return inline_markup(line)


def _heading_text(body: str) -> str:
    """Drop a closing run of `#` (`## Title ##`), in linear time."""
    body = body.rstrip()
    trimmed = body.rstrip("#")
    if trimmed != body and (not trimmed or trimmed[-1].isspace()):
        body = trimmed.rstrip()
    return body


def is_valid_markup(markup: str) -> bool:
    try:
        import gi

        gi.require_version("Pango", "1.0")
        from gi.repository import Pango
    except (ImportError, ValueError):  # pragma: no cover - no GTK, trust the escaping
        return True
    # <a href> is a GtkLabel extension that plain Pango does not know
    checked = _LINK_TAG.sub(lambda m: "</span>" if m.group(0) == "</a>" else "<span>", markup)
    try:
        Pango.parse_markup(checked, -1, "\0")
    except Exception:
        return False
    return True


def prose_markup(text: str) -> str:
    """Markup for one prose block, line by line.

    A line Pango would refuse (crossed `**bold *italic** x*`) is shown as plain
    text; the rest of the block keeps its formatting.
    """
    lines = []
    for line in clean(text).split("\n"):
        markup = _line_markup(line)
        lines.append(markup if is_valid_markup(markup) else html.escape(line, quote=False))
    return "\n".join(lines)


def to_pango(text: str) -> str:
    """The whole answer as one markup string (code kept monospace).

    For places that only have a single label; the panel uses the blocks.
    """
    parts = []
    for block in parse_blocks(text):
        if block.kind == "text":
            parts.append(prose_markup(block.body))
        else:
            parts.append(f'<span font_family="monospace">{html.escape(block.body, quote=False)}</span>')
    return "\n\n".join(parts)
