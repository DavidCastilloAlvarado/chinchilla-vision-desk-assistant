"""Markdown from the model to Pango markup and blocks (no display needed)."""

import pytest

from chinchilla.ui import markdown as md

ANSWER = """Agrega MIN(...) sobre `datetime` para no romper el GROUP BY.

```sql
SELECT
  fsmName,
  MAX(CASE WHEN toState = 'EXECUTING' THEN 1 ELSE 0 END) AS approved
FROM datahub.bronze.aiassistantfsm_brz
WHERE a < 3 AND b > 2;
```

**Qué agregué:**
- first_event_time: timestamp del primer evento de cada entityId.
- event_date: solo la fecha.

**Opcional: una fecha por estado**

```sql
SELECT 1
```"""


def test_the_reported_answer_has_no_stray_backticks():
    blocks = md.parse_blocks(ANSWER)

    assert [block.kind for block in blocks] == ["text", "code", "text", "code"]
    assert blocks[1].lang == "sql"
    assert blocks[1].body.startswith("SELECT\n  fsmName,")
    assert blocks[1].body.endswith("WHERE a < 3 AND b > 2;")
    for block in blocks:
        if block.kind == "text":
            assert "```" not in md.prose_markup(block.body)
    assert "<b>Qué agregué:</b>" in md.prose_markup(blocks[2].body)


def test_code_keeps_its_text_verbatim():
    blocks = md.parse_blocks("```\n**not bold** <tag> `tick` _x_\n```")

    assert blocks == [md.Block("code", "**not bold** <tag> `tick` _x_", "")]


def test_an_unterminated_fence_is_code_while_it_streams():
    blocks = md.parse_blocks("Mira:\n```python\nprint(1)\n")

    assert [block.kind for block in blocks] == ["text", "code"]
    assert blocks[1].lang == "python"
    assert blocks[1].body == "print(1)\n"


def test_tilde_fences_and_longer_closers():
    assert md.parse_blocks("~~~sh\nls\n~~~")[0] == md.Block("code", "ls", "sh")
    assert md.parse_blocks("````\na\n```\nb\n````")[0].body == "a\n```\nb"


def test_tables_become_aligned_columns():
    blocks = md.parse_blocks("| col | other |\n|---|:---:|\n| a | bbb |\n\nafter")

    assert blocks[0].kind == "table"
    assert blocks[0].body.splitlines() == ["col  other", "\u2500\u2500\u2500  \u2500\u2500\u2500\u2500\u2500", "a    bbb"]
    assert blocks[1] == md.Block("text", "after")


def test_a_pipe_line_without_a_rule_is_prose():
    assert md.parse_blocks("| just a pipe |")[0].kind == "text"


@pytest.mark.parametrize(
    "source, expected",
    [
        ("# Title", '<span size="large" weight="bold">Title</span>'),
        ("### Small", '<span size="medium" weight="bold">Small</span>'),
        ("- one", "  \u2022 one"),
        ("* one", "  \u2022 one"),
        ("  - nested", "    \u25e6 nested"),
        ("3. third", "  3. third"),
        ("~~gone~~", "<s>gone</s>"),
        ("__bold__", "<b>bold</b>"),
        ("*it* and _it_", "<i>it</i> and <i>it</i>"),
    ],
)
def test_line_formatting(source, expected):
    assert md.prose_markup(source) == expected


def test_quotes_and_rules():
    assert md.prose_markup("> note").startswith('<span foreground="#8b95a7">\u2502 note')
    assert "\u2500" * 10 in md.prose_markup("---")


def test_snake_case_and_math_are_not_italic():
    markup = md.prose_markup("first_event_time and 2*3*4")

    assert "<i>" not in markup


def test_everything_is_escaped():
    markup = md.prose_markup("<script>alert(1)</script> & **<b>x</b>**")

    assert "<script>" not in markup and "&lt;script&gt;" in markup
    assert "&amp;" in markup
    assert "<b>&lt;b&gt;x&lt;/b&gt;</b>" in markup


def test_links_only_for_http():
    markup = md.prose_markup("[docs](https://example.com/a?b=1&c=2) [x](javascript:alert(1))")

    assert '<a href="https://example.com/a?b=1&amp;c=2">docs</a>' in markup
    assert "javascript" in markup and 'href="javascript' not in markup


def test_inline_code_is_not_formatted_inside():
    markup = md.prose_markup("use `**raw** <x>` here")

    assert "<b>" not in markup
    assert "**raw** &lt;x&gt;" in markup


def test_a_line_pango_would_refuse_falls_back_to_plain_text():
    markup = md.prose_markup("**bold *it** x*\nok **fine**")

    first, second = markup.split("\n")
    assert first == "**bold *it** x*"
    assert second == "ok <b>fine</b>"


@pytest.mark.parametrize(
    "source",
    [
        ANSWER,
        "**unclosed bold and `unclosed code",
        "a < b > c & d <i> </b>",
        "***both***",
        "[a](https://x.y/\"><script>)",
        "> quote with `code` and **bold** and [l](https://e.com)",
        "- **bold `code` _it_** ~~s~~",
    ],
)
def test_prose_is_always_valid_markup(source):
    for block in md.parse_blocks(source):
        if block.kind == "text":
            assert md.is_valid_markup(md.prose_markup(block.body))


def test_to_pango_joins_blocks_for_single_labels():
    markup = md.to_pango("hi **there**\n```\ncode <x>\n```")

    assert "<b>there</b>" in markup
    assert '<span font_family="monospace">code &lt;x&gt;</span>' in markup


def test_nul_bytes_from_the_model_never_break_rendering():
    for source in ("a \x005\x00 b", "`x` \x000\x00 y", "x \x00 <b>y</b>"):
        markup = md.prose_markup(source)
        assert "\x00" not in markup
        assert md.is_valid_markup(markup)
    assert md.parse_blocks("```\nco\x00de\n```")[0].body == "code"


def test_a_link_whose_text_is_code_stays_a_link():
    markup = md.prose_markup("see [`requests.get`](https://docs.example.com/x)")

    assert '<a href="https://docs.example.com/x">' in markup
    assert "requests.get" in markup and "`" not in markup


def test_closing_hashes_are_dropped_from_headings():
    assert md.prose_markup("## Title ##") == '<span size="medium" weight="bold">Title</span>'
    assert md.prose_markup("# C#") == '<span size="large" weight="bold">C#</span>'


@pytest.mark.parametrize(
    "line",
    [
        "## Results" + " " * 1000 + "x",
        "# a" + " " * 3000 + "b",
        "```" + "a" * 5000 + "`",
        "**" * 2000,
        "`" * 3000 + "x",
    ],
)
def test_pathological_lines_render_fast(line):
    import time

    started = time.perf_counter()
    for block in md.parse_blocks(line):
        if block.kind == "text":
            md.prose_markup(block.body)

    assert time.perf_counter() - started < 0.5
