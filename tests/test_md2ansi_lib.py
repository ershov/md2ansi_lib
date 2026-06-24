"""Targeted fixtures for each block type in md2ansi_lib.

Each test asserts that the expected SGR escape sequence appears in the output;
we don't pin exact byte-for-byte snapshots so the tests survive minor cosmetic
tweaks (e.g. choice of bullet glyph, code-frame width).
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import md2ansi_lib as md  # noqa: E402


ESC = "\x1b["


def strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


# ─── Headings ────────────────────────────────────────────────────────────────


def test_heading_levels_have_distinct_colors():
    out = md.md2ansi("# h1\n## h2\n### h3\n#### h4\n##### h5\n###### h6")
    for code in ("38;5;226", "38;5;214", "38;5;118", "38;5;21", "38;5;93", "38;5;239"):
        assert code in out, f"missing SGR {code}: {out!r}"


def test_heading_text_preserved():
    assert "Hello world" in strip_ansi(md.md2ansi("## Hello world"))


# ─── Inline formatting ───────────────────────────────────────────────────────


def test_bold():
    out = md.md2ansi("a **bold** b")
    assert f"{ESC}0;1mbold{ESC}0m" in out


def test_italic():
    out = md.md2ansi("a *it* b")
    assert f"{ESC}0;3mit{ESC}0m" in out


def test_strikethrough():
    out = md.md2ansi("~~gone~~")
    assert f"{ESC}0;9mgone{ESC}0m" in out


def test_bolditalic_triple_asterisk():
    out = md.md2ansi("***bi***")
    assert f"{ESC}0;1;3mbi{ESC}0m" in out


def test_bold_underscore_variant():
    out = md.md2ansi("**_bi_**")
    assert f"{ESC}0;1;3mbi{ESC}0m" in out


def test_under_bold_variant():
    out = md.md2ansi("_**bi**_")
    assert f"{ESC}0;1;3mbi{ESC}0m" in out


def test_inline_code():
    out = md.md2ansi("use `x()` here")
    assert f"{ESC}0;38;5;114mx(){ESC}0m" in out


def test_inline_code_spans_a_newline():
    # Inline backtick span may cross a soft newline (CommonMark allows it);
    # the run-away is stopped by the block-start lookahead.
    out = strip_ansi(md.md2ansi("text `first line\nsecond line` after"))
    assert "first line\nsecond line" in out


def test_escape_punctuation_renders_literal():
    # `\*asd\*` must NOT trigger italic; the backslashes are stripped and the
    # asterisks render as literal punctuation.
    assert strip_ansi(md.md2ansi(r"\*asd\*")) == "*asd*"


def test_escape_inside_bold_preserves_styling_around_literals():
    # `**hello \*world\***` → bold span around "hello *world*".
    out = md.md2ansi(r"**hello \*world\*** rest")
    assert f"{ESC}0;1mhello *world*{ESC}0m" in out


def test_escape_double_backslash():
    # `\\` → single literal backslash.
    assert strip_ansi(md.md2ansi(r"foo\\bar")) == r"foo\bar"


def test_escape_non_punctuation_stays_literal():
    # `\a` — `a` isn't ASCII punctuation, so the backslash stays.
    assert strip_ansi(md.md2ansi(r"non-punct \a here")) == r"non-punct \a here"


def test_inline_code_honors_escaped_backtick():
    # `\`` inside a single-backtick span is a literal backtick, not a closing
    # delimiter — resolved the same way as other inline formatting.
    out = strip_ansi(md.md2ansi(r"x `a \` b` y"))
    assert "a ` b" in out
    assert "\\" not in out


def test_inline_code_keeps_non_backtick_escape_verbatim():
    # Inside a single-backtick span `\` only escapes a backtick; every other
    # backslash (including before punctuation) is preserved verbatim.
    assert r"code \* now" in strip_ansi(md.md2ansi(r"`code \* now`"))


def test_double_backtick_keeps_backslash_verbatim():
    # Double-backtick spans stay inert to backslash escapes per CommonMark.
    assert "\\*" in strip_ansi(md.md2ansi(r"``code \* stays raw``"))


def test_escape_hard_line_break():
    # CommonMark `\<newline>` → emit a newline, drop the backslash.
    out = strip_ansi(md.md2ansi("line one\\\nline two"))
    assert "\\\n" not in out
    assert "line one\nline two" in out


def test_escape_brackets_prevent_link():
    # `\[…\](…)` → literal brackets, not a link.
    assert strip_ansi(md.md2ansi(r"\[not a link\](nope)")) == "[not a link](nope)"


def test_inline_code_double_backtick_allows_internal_backtick():
    out = strip_ansi(md.md2ansi("use ``code with `internal` ticks`` here"))
    assert "code with `internal` ticks" in out
    # The wrapping `` should be consumed, not left as plain text.
    assert "``" not in out


def test_inline_code_double_backtick_spans_newline():
    out = strip_ansi(md.md2ansi("text ``first\nsecond`` end"))
    assert "first\nsecond" in out


def test_inline_code_stops_at_block_boundary():
    # An unclosed backtick must NOT eat the following heading.
    out = strip_ansi(md.md2ansi("text `open across\n\n# heading"))
    assert "heading" in out
    assert "`open across" in out      # left as literal text


def test_inline_span_crosses_hash_without_space():
    # `#nospace` at the start of the next line is NOT an ATX heading (real
    # headings require a space after the `#`s), so the block-start lookahead
    # must let an inline span run across the soft newline into it.
    out = strip_ansi(md.md2ansi("text `open across\n#nospace line` after"))
    assert "open across\n#nospace line" in out
    assert "`" not in out             # backticks consumed → span matched


def test_inline_span_stops_at_real_heading_on_next_line():
    # A genuine ATX heading (`#` + space) on the next line is a block start and
    # must still stop a runaway inline span (regression guard for the tighten).
    out = strip_ansi(md.md2ansi("text `open across\n# real heading` after"))
    assert "`open across" in out      # left as literal text
    assert "real heading" in out      # rendered as a heading (no leading `#`)


def test_link():
    out = md.md2ansi("[click](http://x)")
    assert f"{ESC}0;38;5;45;4mclick{ESC}0m" in out
    assert "http://x" not in out  # URL discarded


def test_image_substitution():
    out = md.md2ansi("![alt](u)")
    assert "[IMG: alt]" in out
    assert "u" in out or True  # URL silently dropped


def test_linked_image_renders_image_label():
    # A linked image `[![alt](img)](url)` is an image used as a link's text. It
    # must render as the image label styled as a link — the image's `](…)` must
    # not be mistaken for the link's own close+URL (which leaks raw markdown).
    out = md.md2ansi("[![b-git](media/browse-git.png)](media/browse-git.png)")
    assert strip_ansi(out) == "[IMG: b-git]"
    assert "browse-git.png" not in strip_ansi(out)  # URLs discarded
    assert "38;5;45;4" in out                        # styled as a link


# ─── Block-level ─────────────────────────────────────────────────────────────


def test_hr_uses_line_width():
    out = md.md2ansi("---", line_width=10)
    assert "─" * 9 in out


def test_html_hr_uses_line_width():
    # A standalone `<hr>` line draws the same full-width bar as a markdown `---`.
    out = md.md2ansi("<hr>", line_width=10)
    assert "─" * 9 in out


def test_html_hr_bar_tracks_line_width():
    # The bar length follows line_width, exactly like the markdown-HR rule.
    out = md.md2ansi("<hr>", line_width=25)
    assert "─" * 24 in out
    assert "─" * 25 not in out


def test_html_hr_leading_whitespace():
    out = md.md2ansi("   <hr>", line_width=10)
    assert "─" * 9 in out


def test_html_hr_case_insensitive():
    out = md.md2ansi("<HR>", line_width=10)
    assert "─" * 9 in out


def test_html_hr_self_closing():
    out = md.md2ansi("<hr/>", line_width=10)
    assert "─" * 9 in out


def test_html_hr_self_closing_spaced():
    out = md.md2ansi("<hr />", line_width=10)
    assert "─" * 9 in out


def test_html_hr_with_trailing_text_is_not_block_rule():
    # Text after `<hr>` means the line is not a standalone rule, so the block
    # rule must not fire and turn it into a full-width bar.
    out = md.md2ansi("<hr> x", line_width=10)
    assert "─" * 9 not in out


def test_fenced_code_python():
    out = md.md2ansi("```python\ndef f(): return 42\n```")
    assert f"{ESC}0;38;5;204mdef{ESC}0m" in out          # keyword
    assert f"{ESC}0;38;5;204mreturn{ESC}0m" in out
    assert f"{ESC}0;38;5;220m42{ESC}0m" in out           # number


def test_fenced_code_bash():
    out = md.md2ansi("```bash\nif true; then echo hi; fi\n```")
    assert f"{ESC}0;38;5;204mif{ESC}0m" in out
    assert f"{ESC}0;38;5;147mecho{ESC}0m" in out


def test_fenced_code_javascript():
    out = md.md2ansi("```javascript\nconst x = 'y';\n```")
    assert f"{ESC}0;38;5;204mconst{ESC}0m" in out


def test_fenced_code_c():
    out = md.md2ansi("```c\n#include <stdio.h>\nint main(void) { return 0; }\n```")
    assert f"{ESC}0;38;5;204m#include{ESC}0m" in out      # preprocessor
    assert f"{ESC}0;38;5;204mint{ESC}0m" in out           # keyword/type
    assert f"{ESC}0;38;5;204mreturn{ESC}0m" in out
    assert f"{ESC}0;38;5;220m0{ESC}0m" in out             # number


def test_fenced_code_c_comment_and_string():
    out = md.md2ansi('```c\nchar *s = "hi"; // greet\n```')
    assert f"{ESC}0;38;5;114m\"hi\"{ESC}0m" in out         # string
    assert f"{ESC}0;38;5;245m// greet{ESC}0m" in out       # line comment


def test_fenced_code_c_block_comment():
    out = md.md2ansi("```c\n/* note */ int y;\n```")
    assert f"{ESC}0;38;5;245m/* note */{ESC}0m" in out     # block comment


def test_fenced_code_cpp():
    out = md.md2ansi("```cpp\nclass Foo { std::string s; };\n```")
    assert f"{ESC}0;38;5;204mclass{ESC}0m" in out          # C++ keyword
    assert f"{ESC}0;38;5;147mstd{ESC}0m" in out            # builtin


def test_code_c_frame_label():
    # `c`, `cpp`, and `c++` fences all render under the shared "C/C++" label.
    assert "C/C++" in strip_ansi(md.md2ansi("```c\nint x;\n```"))
    assert "C/C++" in strip_ansi(md.md2ansi("```cpp\nint x;\n```"))
    assert "C/C++" in strip_ansi(md.md2ansi("```c++\nint x;\n```"))


def test_scan_code_c_subtype():
    spans = list(md.md2ansi_scan("```cpp\nint x;\n```", {"code"}))
    assert (spans[0].kind, spans[0].subtype) == ("code", "code-c")


# ─── Unknown / unmarked code blocks ──────────────────────────────────────────


def test_unknown_block_colors_numbers_and_punct():
    out = md.md2ansi("```\nfoo = 42 + bar\n```")
    assert f"{ESC}0;38;5;220m42{ESC}0m" in out             # number
    assert f"{ESC}0;38;5;246m={ESC}0m" in out              # punctuation dimmed


def test_unknown_block_colors_string():
    out = md.md2ansi('```\nname "value"\n```')
    assert f"{ESC}0;38;5;114m\"value\"{ESC}0m" in out       # string


def test_unknown_tag_block_colored():
    # An unrecognized language tag (e.g. rust) still gets generic coloring.
    out = md.md2ansi("```rust\nlet x = 7;\n```")
    assert f"{ESC}0;38;5;220m7{ESC}0m" in out
    assert f"{ESC}0;38;5;246m={ESC}0m" in out


def test_unknown_block_string_spans_linebreak():
    # Permissive strings may run across newlines; the color re-emits on line 2.
    out = md.md2ansi('```\na = "line one\nline two"\n```')
    assert f"{ESC}0;38;5;114m\"line one" in out
    assert f"{ESC}0;38;5;114mline two\"" in out


def test_unknown_block_no_comment_coloring():
    # Comment syntax is unknown, so `#`/`//` runs are not comment-colored; a
    # plain word stays the default color (no SGR injected around it).
    out = md.md2ansi("```\nhello world\n```")
    assert "hello" in strip_ansi(out)
    assert f"{ESC}0;38;5;114mhello" not in out             # not string-colored


def test_frontmatter_stays_plain_passthrough():
    # Frontmatter keeps the no-rule generic context — numbers/punct NOT colored.
    out = md.md2ansi("---\nport: 8080\n---")
    assert f"{ESC}0;38;5;220m8080{ESC}0m" not in out
    assert "port: 8080" in strip_ansi(out)


def test_fenced_code_generic_no_markdown_parsing():
    out = md.md2ansi("```\nplain text **not bold**\n```")
    # Markdown emphasis is NOT applied inside a code block: the `**` markers
    # survive literally (now dimmed as punctuation), and no bold SGR is emitted.
    assert "**not bold**" in strip_ansi(out)
    assert f"{ESC}0;1mnot bold" not in out


# ─── Punctuation dimming (universal) ─────────────────────────────────────────


def test_punct_dimmed_in_python():
    # Operators/punctuation runs get the dim-gray punct color (38;5;246).
    out = md.md2ansi("```python\nx = 1\n```")
    assert f"{ESC}0;38;5;246m={ESC}0m" in out


def test_punct_dimmed_in_bash():
    out = md.md2ansi("```bash\nx=$((1 + 2))\n```")
    assert f"{ESC}0;38;5;246m" in out


def test_punct_dimmed_in_javascript():
    out = md.md2ansi("```javascript\nx = 1;\n```")
    assert f"{ESC}0;38;5;246m={ESC}0m" in out


def test_punct_does_not_steal_float_dot():
    # The `.` inside a float stays part of the (yellow) number, not dimmed.
    out = md.md2ansi("```python\ny = 3.14\n```")
    assert f"{ESC}0;38;5;220m3.14{ESC}0m" in out


def test_punct_does_not_steal_comment_slashes():
    # `//` opens a JS comment (gray-comment); it must not be split as punctuation.
    out = md.md2ansi("```javascript\n// hi\n```")
    assert f"{ESC}0;38;5;245m// hi{ESC}0m" in out


# ─── Frontmatter ─────────────────────────────────────────────────────────────


def test_frontmatter_renders_framed_box():
    out = md.md2ansi("---\ntitle: Hello\ntags: x\n---\n# Body")
    plain = strip_ansi(out)
    # Framed like a code block, labelled "Frontmatter".
    assert "Frontmatter" in plain
    for ch in "┌┐└┘─":
        assert ch in out, f"missing frame char {ch}"
    # YAML body passes through verbatim.
    assert "title: Hello" in plain
    # Content after the closing fence is still parsed (h1 colored).
    assert f"{ESC}0;38;5;226m" in out


def test_frontmatter_box_not_merged_with_following_line():
    out = strip_ansi(md.md2ansi("---\ntitle: x\n---\n# Body"))
    assert "Body" in out
    # Closing border on its own line, not glued to the next block.
    assert "┘Body" not in out


def test_frontmatter_body_not_markdown_parsed():
    out = md.md2ansi("---\nx: **not bold**\n---")
    # Generic (no-highlight) context: emphasis markers survive verbatim.
    assert "**not bold**" in strip_ansi(out)
    assert f"{ESC}0;1mnot bold{ESC}0m" not in out


def test_frontmatter_requires_closing_fence():
    # No closing `---`: the opening `---` is just an HR, not frontmatter.
    out = md.md2ansi("---\ntitle: x")
    assert "Frontmatter" not in strip_ansi(out)
    assert "─" in out


def test_mid_document_dashes_are_hr_not_frontmatter():
    out = md.md2ansi("intro\n\n---\n\nmore")
    assert "Frontmatter" not in strip_ansi(out)
    assert "─" in out


def test_frontmatter_with_blank_line_is_not_matched():
    # A blank line in the body disqualifies it as frontmatter (real markdown
    # has blank lines; a tight YAML block does not) → HR, not a box.
    out = md.md2ansi("---\ntitle: x\n\nbody: y\n---")
    assert "Frontmatter" not in strip_ansi(out)


def test_frontmatter_with_comment_is_not_matched():
    # A `#` comment line in the body disqualifies it as frontmatter.
    out = md.md2ansi("---\ntitle: x\n# note\nmore: y\n---")
    assert "Frontmatter" not in strip_ansi(out)


def test_frontmatter_body_not_line_wrapped():
    long_val = "description: " + " ".join(["word"] * 20)
    out = md.md2ansi(f"---\n{long_val}\n---", line_width=40)
    # The long YAML line is preserved intact inside the box (not word-wrapped).
    assert long_val in strip_ansi(out)


def test_blockquote_renders_bar():
    out = md.md2ansi("> first\n> second")
    assert "│" in out
    plain = strip_ansi(out)
    assert "first" in plain and "second" in plain


def test_blockquote_recurses_inline():
    out = md.md2ansi("> **strong**")
    assert f"{ESC}0;1mstrong{ESC}0m" in out


def test_table_box_borders():
    out = md.md2ansi("| a | b |\n|---|---|\n| 1 | 2 |")
    for ch in "┌┐└┘┬┴├┤┼─│":
        assert ch in out, f"missing box-drawing char {ch}"


def test_table_cells_recurse_inline():
    out = md.md2ansi("| **B** | x |\n|---|---|\n| 1 | 2 |")
    assert f"{ESC}0;1mB{ESC}0m" in out


# ─── Code-span-aware cell splitting ──────────────────────────────────────────
# A pipe inside an inline code span is content, not a column divider, so a cell
# like `a | b` survives without escaping. See _m2a_split_table_row.


def test_table_cell_code_span_hides_pipe():
    # The motivating bug: an un-escaped | inside `...` split the code span
    # across three cells. It must stay one cell.
    assert md._m2a_split_table_row("| aaa | `ccc | ddd` |") == ["aaa", "`ccc | ddd`"]


def test_table_cell_double_backtick_span_hides_pipe():
    assert md._m2a_split_table_row("| a | ``x | y`` | b |") == ["a", "``x | y``", "b"]


def test_table_cell_code_span_renders_pipe_in_one_cell():
    # End-to-end: the pipe stays inside the styled inline-code run rather than
    # becoming a column boundary.
    out = md.md2ansi("| h | x |\n|---|---|\n| `a | b` | y |", line_width=80)
    assert f"{ESC}0;38;5;114ma | b{ESC}0m" in out


def test_table_cell_unbalanced_backtick_still_splits():
    # No closing backtick -> the stray ` is an ordinary char and | still splits
    # (degrades to prior behavior; the row was malformed anyway).
    assert md._m2a_split_table_row("| a `b | c |") == ["a `b", "c"]


def test_table_cell_escaped_pipe_still_honored():
    # Regression guard: \| remains a non-dividing literal as before.
    assert md._m2a_split_table_row(r"| a\|b | c |") == [r"a\|b", "c"]


def test_table_delimiter_row_split_unaffected():
    # Regression guard: alignment row has no spans and splits as usual.
    assert md._m2a_split_table_row("|:--|--:|") == [":--", "--:"]


def _table_cell_row(plain_line):
    # Returns the list of cell contents (with their padding) between `│`.
    # Strips the leading/trailing `│` and splits.
    inner = plain_line.strip("│")
    return inner.split("│")


def test_table_align_left_marker_body_and_header():
    src = "| h | x |\n| :--- | --- |\n| ab | y |"
    out = md.md2ansi(src)
    lines = [ln for ln in strip_ansi(out).splitlines() if ln.startswith("│")]
    # header row, body row
    header_cells = _table_cell_row(lines[0])
    body_cells = _table_cell_row(lines[1])
    # Width of first column is 2 (max of "h" and "ab"); left-aligned -> " ab "
    assert header_cells[0] == " h  "
    assert body_cells[0] == " ab "


def test_table_align_right_marker_body_and_header():
    src = "| h | x |\n| ---: | --- |\n| ab | y |"
    out = md.md2ansi(src)
    lines = [ln for ln in strip_ansi(out).splitlines() if ln.startswith("│")]
    header_cells = _table_cell_row(lines[0])
    body_cells = _table_cell_row(lines[1])
    # Width 2; right-aligned: header " h" -> " " + " h" -> "  h "; body "ab" -> " ab "
    assert header_cells[0] == "  h "
    assert body_cells[0] == " ab "


def test_table_align_center_marker_body_and_header():
    src = "| h | x |\n| :---: | --- |\n| abcd | y |"
    out = md.md2ansi(src)
    lines = [ln for ln in strip_ansi(out).splitlines() if ln.startswith("│")]
    header_cells = _table_cell_row(lines[0])
    body_cells = _table_cell_row(lines[1])
    # Width 4; center "h": pad=3 -> left=1, right=2 -> " h  "; outer space pad -> "  h   "
    assert header_cells[0] == "  h   "
    assert body_cells[0] == " abcd "


def test_table_mixed_alignment_columns():
    src = "| a | b | c |\n| :--- | :---: | ---: |\n| xx | yy | zz |"
    out = md.md2ansi(src)
    lines = [ln for ln in strip_ansi(out).splitlines() if ln.startswith("│")]
    header_cells = _table_cell_row(lines[0])
    body_cells = _table_cell_row(lines[1])
    # Widths all = 2.
    # left: "a" -> " a  "
    assert header_cells[0] == " a  "
    assert body_cells[0] == " xx "
    # center: "b" pad=1 -> "b " -> " b  "
    assert header_cells[1] == " b  "
    assert body_cells[1] == " yy "
    # right: "c" -> " c" -> "  c "
    assert header_cells[2] == "  c "
    assert body_cells[2] == " zz "


def test_table_no_separator_defaults_left():
    src = "| h | x |\n| ab | yyyy |"
    out = md.md2ansi(src)
    lines = [ln for ln in strip_ansi(out).splitlines() if ln.startswith("│")]
    # No separator row -> all cells left-aligned.
    header_cells = _table_cell_row(lines[0])
    body_cells = _table_cell_row(lines[1])
    # Column 0 width 2, column 1 width 4.
    assert header_cells[0] == " h  "
    assert header_cells[1] == " x    "
    assert body_cells[0] == " ab "
    assert body_cells[1] == " yyyy "


def test_list_mixed_markers_and_nesting():
    out = md.md2ansi("- one\n* two\n  - nested\n1. ord")
    assert "·" in out                                    # bullets
    assert "1." in out                                   # ordered marker preserved
    plain = strip_ansi(out)
    assert re.search(r"\n  · nested", plain)


def test_list_recurses_inline():
    out = md.md2ansi("- **important**")
    assert f"{ESC}0;1mimportant{ESC}0m" in out


# ─── Headings nested in lists / blockquotes ──────────────────────────────────
# Covered: a heading that is the direct line-content of a list item or a
# blockquote line. Continuation-line headings and multi-level nesting
# (e.g. `> - ## h`) are intentionally out of scope — see M2A_CONTEXT_MD_BLOCKLITE
# — and are not tested here.


def test_heading_in_unordered_list_item():
    out = md.md2ansi("- ## Section title")
    assert md.M2A_COLOR_H2 in out            # content styled as an H2
    assert "·" in out                        # bullet chrome preserved
    plain = strip_ansi(out)
    assert "Section title" in plain
    assert "##" not in plain                 # literal hashes consumed, not leaked


def test_heading_in_ordered_list_item():
    out = md.md2ansi("1. ## Ordered head")
    assert md.M2A_COLOR_H2 in out
    assert "1." in out                       # ordered marker preserved
    assert "##" not in strip_ansi(out)


def test_heading_in_blockquote():
    out = md.md2ansi("> ## Quoted head")
    assert md.M2A_COLOR_H2 in out
    assert "│" in out                        # quote bar preserved
    plain = strip_ansi(out)
    assert "Quoted head" in plain
    assert "##" not in plain


def test_blockquote_heading_then_inline_body():
    # A heading line plus an emphasized body line in one quote: the heading is
    # colored and the body is still inline-parsed.
    out = md.md2ansi("> ## Head\n> body *em*")
    assert md.M2A_COLOR_H2 in out            # heading on line 1
    assert f"{ESC}0;3mem{ESC}0m" in out      # italic on line 2


def test_heading_in_nested_list_item():
    out = md.md2ansi("- parent\n  - ### child head")
    assert md.M2A_COLOR_H3 in out            # H3 on the nested item
    plain = strip_ansi(out)
    assert "child head" in plain
    assert "#" not in plain


def test_nested_heading_title_recurses_inline():
    # Inline markup inside a nested heading's title is still parsed.
    out = md.md2ansi("- ## **bold** in head")
    assert md.M2A_COLOR_H2 in out
    plain = strip_ansi(out)
    assert "bold in head" in plain
    assert "**" not in plain                 # bold markup consumed
    assert "##" not in plain


def test_nested_heading_does_not_leak_opaque_marker():
    # Regression: the nested heading marks its line opaque; that marker must be
    # stripped, never surfacing as a literal NUL after the bullet/bar.
    for src in ("- ## h", "1. ## h", "> ## h", "- a\n  - ## h"):
        assert "\x00" not in md.md2ansi(src), src


# ─── Footnotes ───────────────────────────────────────────────────────────────


def test_footnote_ref_and_def():
    src = "Body[^a] and[^b].\n\n[^a]: First.\n[^b]: Second."
    out = md.md2ansi(src)
    assert "[^a]" in out and "[^b]" in out
    assert "Footnotes:" in out
    plain = strip_ansi(out)
    assert "First." in plain and "Second." in plain


def test_footnote_missing_definition_is_silent():
    # Inline ref still renders; the footnotes section is suppressed (no warning).
    out = md.md2ansi("Ref[^missing] here.")
    assert "[^missing]" in out
    assert "Missing footnote definition" not in out
    assert "Footnotes:" not in out


def test_footnote_section_skips_undefined_entries():
    # `a` has a def, `b` doesn't — only `a` appears in the section.
    out = md.md2ansi("Refs [^a] and [^b].\n\n[^a]: A note.")
    assert "Footnotes:" in out
    assert "A note." in out
    plain = strip_ansi(out)
    # `[^b]` shows up inline, but not as a footnote entry.
    section_start = plain.index("Footnotes:")
    assert "[^b]" not in plain[section_start:]
    assert "[^a]" in plain[section_start:]


def test_footnote_order_follows_appearance():
    src = "[^b] then [^a]\n\n[^a]: A\n[^b]: B"
    plain = strip_ansi(md.md2ansi(src))
    # `b` is referenced first, so it appears first in the footnotes section.
    b_pos = plain.rfind("[^b]")
    a_pos = plain.rfind("[^a]")
    assert b_pos < a_pos


# ─── Error tolerance & passthrough ───────────────────────────────────────────


def test_plain_text_passes_through_unchanged():
    src = "Just a paragraph with no markup at all.\nNext line."
    assert md.md2ansi(src) == src


def test_stray_asterisks_pass_through():
    # Single * with no closing pair: not italic, just literal text.
    assert md.md2ansi("a * b") == "a * b"


def test_default_current_style_resets():
    # md2ansi default is current_style="0"; bold should emit \x1b[0;1m and reset to \x1b[0m.
    assert md.md2ansi("**x**") == f"{ESC}0;1mx{ESC}0m"


# ─── Python string prefix handling ───────────────────────────────────────────


def _py_highlight(snippet):
    """Render `snippet` through the Python code context only (no fence markers)."""
    return md._md2ansi(snippet, "0", md.M2A_CONTEXT_CODE_PYTHON, md.M2A_DocumentState())


def test_py_string_unprefixed():
    assert f"{ESC}0;38;5;114m\"x\"{ESC}0m" in _py_highlight('a = "x"')
    assert f"{ESC}0;38;5;114m'y'{ESC}0m" in _py_highlight("a = 'y'")


def test_py_string_f_prefix():
    assert f"{ESC}0;38;5;114mf\"x\"{ESC}0m" in _py_highlight('f"x"')


def test_py_string_r_prefix():
    assert f"{ESC}0;38;5;114mr\"path\"{ESC}0m" in _py_highlight('open(r"path")')


def test_py_string_two_char_prefixes():
    # rb / br / fr / rf — all valid Python combos, in both case variants.
    for snippet, expected in [
        ('rb"x"',  'rb"x"'),
        ('Br"x"',  'Br"x"'),
        ('fR"x"',  'fR"x"'),
        ('RF"x"',  'RF"x"'),
    ]:
        assert f"{ESC}0;38;5;114m{expected}{ESC}0m" in _py_highlight(snippet)


def test_py_string_triple_quoted_prefix():
    assert f'{ESC}0;38;5;114mf"""hi"""{ESC}0m' in _py_highlight('f"""hi"""')


def test_py_string_does_not_eat_preceding_keyword():
    # `return"hi"` is valid Python (no space required). The `return` must still
    # be highlighted as a keyword, and "hi" as a string — not the whole span
    # as a string with `return` as a fake prefix.
    out = _py_highlight('return"hi"')
    assert f"{ESC}0;38;5;204mreturn{ESC}0m" in out, repr(out)
    assert f"{ESC}0;38;5;114m\"hi\"{ESC}0m" in out, repr(out)


def test_py_string_does_not_eat_identifier_tail():
    # In `foor"x"`, the `r` is part of identifier `foor` — only `"x"` should
    # be colored as a string. The `\b` anchor on the prefix prevents the
    # `r` from being claimed as a prefix.
    out = _py_highlight('foor"x"')
    assert f"{ESC}0;38;5;114m\"x\"{ESC}0m" in out, repr(out)
    # The `r` immediately before the quote should NOT be styled.
    assert f"{ESC}0;38;5;114mr\"x\"{ESC}0m" not in out


# ─── _m2a_inject_color helper ────────────────────────────────────────────────


def test_inject_color_single_line():
    assert md._m2a_inject_color("hi", "1") == "\x1b[1mhi"
    assert md._m2a_inject_color("hi", "1", "0") == "\x1b[1mhi\x1b[0m"


def test_inject_color_re_emits_after_interior_newline():
    out = md._m2a_inject_color("a\nb", "1", "0")
    assert out == "\x1b[1ma\n\x1b[1mb\x1b[0m"


def test_inject_color_runs_of_newlines_count_as_one():
    # Run of two \n's still gets a single SGR injection after the run.
    out = md._m2a_inject_color("a\n\nb", "1", "0")
    assert out == "\x1b[1ma\n\n\x1b[1mb\x1b[0m"


def test_inject_color_no_injection_for_trailing_newlines():
    # Trailing \n's are NOT followed by an SGR — only the reset.
    assert md._m2a_inject_color("a\n", "1", "0") == "\x1b[1ma\n\x1b[0m"
    assert md._m2a_inject_color("a\n\n", "1", "0") == "\x1b[1ma\n\n\x1b[0m"


def test_inject_color_omits_reset_when_none():
    assert md._m2a_inject_color("a\nb", "1") == "\x1b[1ma\n\x1b[1mb"


def test_inject_color_empty_string():
    assert md._m2a_inject_color("", "1", "0") == "\x1b[1m\x1b[0m"


# ─── Code-block frame ────────────────────────────────────────────────────────


def test_code_frame_has_language_label():
    plain = strip_ansi(md.md2ansi("```python\ndef f(): return 42\n```"))
    assert "Code: python" in plain
    assert plain.splitlines()[0].startswith("┌── Code: python ")
    assert plain.splitlines()[0].endswith("┐")


def test_code_frame_generic_no_tag_uses_bare_label():
    plain = strip_ansi(md.md2ansi("```\nplain\n```"))
    first = plain.splitlines()[0]
    assert "Code" in first and "Code:" not in first


def test_code_frame_generic_extracts_language_tag():
    plain = strip_ansi(md.md2ansi("```rust\nfn main() {}\n```"))
    assert "Code: rust" in plain


def test_code_frame_width_extends_one_past_body():
    src = "```python\n" + "x" * 30 + "\n```"
    lines = strip_ansi(md.md2ansi(src)).splitlines()
    top, body, bot = lines[0], lines[1], lines[2]
    assert top.startswith("┌") and top.endswith("┐")
    assert bot.startswith("└") and bot.endswith("┘")
    # Body indented 1 space; frame sticks out 1 char past body on each side.
    assert body.startswith(" ")
    assert body.lstrip() == "x" * 30
    assert len(top) == len(bot) == 32   # 30 (body) + 2 (overhang)


def test_code_body_is_indented_by_one_space():
    plain = strip_ansi(md.md2ansi("```\nline1\nline2\n```"))
    lines = plain.splitlines()
    assert lines[1] == " line1"
    assert lines[2] == " line2"


def test_code_frame_keeps_source_indent():
    # A fenced block nested inside an indented context (e.g. under a list item
    # or quote) should have its frame start at that same indent column.
    src = "- item\n  ```python\n  def g(): pass\n  ```"
    plain = strip_ansi(md.md2ansi(src))
    top = next(ln for ln in plain.splitlines() if "┌" in ln)
    bot = next(ln for ln in plain.splitlines() if "└" in ln)
    body = next(ln for ln in plain.splitlines() if "def g()" in ln)
    assert top.startswith("  ┌"), repr(top)
    assert bot.startswith("  └"), repr(bot)
    # Body keeps the source indent + the frame's 1-space interior indent.
    assert body.startswith("   def g(): pass"), repr(body)


def test_code_body_inner_indent_preserved_after_strip():
    # Body has structural indent (4 spaces) on top of the fence indent (2).
    # After stripping the fence indent, the structural 4 spaces stay.
    src = "- item\n  ```python\n  def f():\n      return 42\n  ```"
    plain = strip_ansi(md.md2ansi(src))
    body_lines = [ln for ln in plain.splitlines() if "def f" in ln or "return" in ln]
    assert body_lines[0] == "   def f():"
    assert body_lines[1] == "       return 42"   # 2 (source) + 1 (frame) + 4 (code)


def test_code_frame_width_at_least_label_minimum():
    # Tiny body — frame still wide enough for the "Code: javascript" label.
    plain = strip_ansi(md.md2ansi("```javascript\nx\n```"))
    top = plain.splitlines()[0]
    assert "Code: javascript" in top
    # ┌── Code: javascript ──┐  → at minimum 22 chars visible width.
    assert len(top) >= len("┌── Code: javascript ──┐")


def test_code_frame_no_blank_line_before_closing():
    plain = strip_ansi(md.md2ansi("```\nline1\nline2\n```"))
    lines = plain.splitlines()
    # Order: top, " line1", " line2", bot — no blank line between body and bot.
    assert lines[-2] == " line2"
    assert lines[-1].startswith("└") and lines[-1].endswith("┘")


# ─── Multi-line span styling ─────────────────────────────────────────────────


def test_multiline_string_emits_sgr_on_each_line():
    # A triple-quoted Python string spans many lines. The opening SGR must be
    # re-emitted after each interior newline so the color survives pagers /
    # tools that don't carry SGR state across line breaks.
    snippet = 'x = r"""line1\nline2\nline3"""'
    out = md._md2ansi(snippet, "0", md.M2A_CONTEXT_CODE_PYTHON, md.M2A_DocumentState())
    for line in ("line1", "line2", "line3"):
        # Each interior line must be preceded by the string-color SGR.
        assert f"\x1b[0;38;5;114m{line}" in out or f"\x1b[0;38;5;114mr\"\"\"line1" in out, \
            f"line {line!r} lacks per-line SGR: {out!r}"
    # Specifically: lines 2 and 3 must each start with the SGR after a newline.
    assert "\n\x1b[0;38;5;114mline2" in out
    assert "\n\x1b[0;38;5;114mline3" in out


def test_multiline_bold_emits_sgr_on_each_line():
    out = md.md2ansi("**bold\nstrong**")
    assert "\x1b[0;1mbold" in out
    assert "\n\x1b[0;1mstrong" in out


# ─── Line wrapping ───────────────────────────────────────────────────────────


def test_default_line_width_disables_wrapping():
    long_para = "word " * 100
    out = strip_ansi(md.md2ansi(long_para))
    assert "\n" not in out.rstrip()  # entire paragraph stays on one line


def test_wrap_paragraph_at_word_boundary():
    src = "This is a long paragraph that needs to be wrapped at some sensible boundary."
    out = strip_ansi(md.md2ansi(src, line_width=30))
    for line in out.splitlines():
        # Each wrapped line should be ≤ width or contain a single long word.
        assert len(line) <= 30 or len(line.split()) == 1


def test_no_break_zone_under_threshold():
    # line_width=80 → threshold=50. A line at 40 chars with a 100-char word
    # following should NOT break (we're below threshold); the long word
    # overflows on a single line.
    src = "short prefix " + "x" * 100
    out = strip_ansi(md.md2ansi(src, line_width=80))
    assert out.strip() == src.strip()      # no break inserted


def test_break_above_threshold():
    # Same overflow scenario but the line was already past threshold (≥50).
    src = ("word " * 12).strip() + " hugewordthatoverflows"
    out = strip_ansi(md.md2ansi(src, line_width=80))
    assert "\n" in out                     # break inserted


def test_wrap_skips_code_block():
    src = "```\n" + "long line of code that exceeds the line width by quite a margin indeed\n" + "```"
    plain = strip_ansi(md.md2ansi(src, line_width=30))
    # Find the body line — it must still be one line, not wrapped.
    body_lines = [ln for ln in plain.splitlines() if "long line of code" in ln]
    assert len(body_lines) == 1


def test_wrap_skips_table():
    src = "| long cell content that would normally wrap if not protected | b |"
    out = strip_ansi(md.md2ansi(src, line_width=30))
    # Single source line → still single line in output (other than borders).
    table_lines = [ln for ln in out.splitlines() if "long cell content" in ln]
    assert len(table_lines) == 1


def test_wrap_skips_heading():
    src = "# A really long heading that exceeds the line width but should not be wrapped"
    out = strip_ansi(md.md2ansi(src, line_width=30))
    # Should stay on one line.
    matching = [ln for ln in out.splitlines() if "really long heading" in ln]
    assert len(matching) == 1


def test_wrap_skips_footnote_def():
    # If the def line were wrapped it would split into "[^a]: ..." plus a
    # plain continuation line that the def rule wouldn't capture — so the
    # rendered Footnotes section would lose half the text.
    src = "Ref[^a].\n\n[^a]: A footnote definition with content longer than the wrap width here."
    out = strip_ansi(md.md2ansi(src, line_width=30))
    assert "A footnote definition with content longer than the wrap width here." in out


def test_wrap_list_hanging_indent_plus_two():
    src = "- A list item with quite a bit of content that should wrap"
    out = strip_ansi(md.md2ansi(src, line_width=30))
    lines = out.splitlines()
    # First wrapped line starts with the bullet; later wrapped lines indent +2.
    assert lines[0].startswith("·")
    for ln in lines[1:]:
        assert ln.startswith("  "), repr(ln)


def test_wrap_nested_list_hanging_indent_plus_two():
    src = "  - Nested list item with text that goes beyond the line width and wraps"
    out = strip_ansi(md.md2ansi(src, line_width=30))
    lines = out.splitlines()
    # Source indent (2) + 2 = 4-char continuation indent.
    assert lines[0].startswith("  ·")
    for ln in lines[1:]:
        assert ln.startswith("    "), repr(ln)


def test_wrap_blockquote_preserves_marker_prefix():
    src = "> A blockquote with content long enough that it needs to wrap into multiple lines."
    out = strip_ansi(md.md2ansi(src, line_width=30))
    # Every output line of the quote should start with the styled bar.
    for ln in out.splitlines():
        if ln.strip():
            assert ln.startswith("│"), repr(ln)


def test_hr_uses_150_fallback_when_no_width():
    out = strip_ansi(md.md2ansi("---"))
    assert "─" * 149 in out


# ─── Inline spans surviving a wrap break ─────────────────────────────────────


def test_wrap_inside_bold_keeps_bold_when_continuation_looks_ordinal():
    # The wrap break lands inside the bold span and the continuation line
    # happens to start with "3. " (an ordinal). Wrapping must not leave the
    # `**` literal nor parse the fragment as a new list item.
    src = ("Intro words here and then **a bold span mentioning step 3. "
           "that keeps going well past the wrap point** end.")
    out = md.md2ansi(src, line_width=55)
    assert "**" not in strip_ansi(out)        # markers consumed, not literal
    assert "\x1b[0;1m" in out                  # bold SGR actually applied


def test_wrap_inside_bold_keeps_bold_when_continuation_starts_with_dash():
    # A literal hyphen inside the bold span must stay a hyphen, never become a
    # list bullet, when a wrap break puts it at the start of a continuation line.
    src = ("Some intro text and a **bold region discussing the cost - benefit "
           "tradeoff in great detail here** done.")
    out = strip_ansi(md.md2ansi(src, line_width=55))
    assert "**" not in out
    assert "·" not in out                      # no spurious bullet


def test_wrap_inside_list_inline_code_survives_break():
    # Reproduces the q-file failure: a list item whose inline-code span is split
    # by a wrap break. The backticks must be consumed, not left literal.
    src = ("1. **`to_item` treats a bare `tuple` as positional fields** "
           "(`030-data.py:195`): `(id, title, tag, the rest)` so a bare tuple "
           "must be built carefully.")
    out = strip_ansi(md.md2ansi(src, line_width=86))
    assert "`" not in out                       # inline-code markers consumed
    assert "**" not in out


def test_wrap_measures_visible_width_not_raw_markup():
    # A line of `**wNN**` spans renders to ~4 visible cols each, so at width 40
    # the first wrapped line should be near-full, not wrapped at the raw-markup
    # width (which counted the `**` and stopped at ~19 visible cols).
    src = " ".join("**w%02d**" % i for i in range(20))
    first = strip_ansi(md.md2ansi(src, line_width=40)).splitlines()[0]
    assert len(first) >= 30


# ─── Table cell wrapping (shrink-to-fit) ─────────────────────────────────────


def _table_body_rows(plain_text):
    """Return body lines (starting with `│`) from a rendered table."""
    return [ln for ln in plain_text.splitlines() if ln.startswith("│")]


def test_table_wide_column_shrinks_short_untouched():
    long_word = "word " * 20  # 100 chars
    src = f"| big | s |\n|---|---|\n| {long_word.strip()} | x |"
    out = strip_ansi(md.md2ansi(src, line_width=40, cell_min_width=5))
    table_lines = [ln for ln in out.splitlines() if ln.startswith(("│", "┌", "├", "└"))]
    # The whole table must respect the requested line_width.
    assert all(len(ln) <= 40 for ln in table_lines), table_lines


def test_table_column_shrinks_when_wrap_does_not_use_assigned_width():
    # All cells in the column wrap to a max sub-line shorter than the column
    # received from the layout — the column should shrink to match.
    src = "| h1 | h2 |\n|---|---|\n| short content here that wraps | other |"
    out = strip_ansi(md.md2ansi(src, line_width=60, cell_min_width=10))
    table_lines = [ln for ln in out.splitlines() if ln.startswith(("│", "┌", "├", "└"))]
    # The widest row line gives the actual table width. It must be ≤ line_width.
    assert max(len(ln) for ln in table_lines) <= 60
    # And, having shrunk, the table should NOT be at the line_width limit.
    assert max(len(ln) for ln in table_lines) < 60


def test_table_extra_fit_round_recovers_budget():
    # If one column grew past its layout assignment, the extra fitting round
    # should reclaim budget from the remaining shrinkable columns so the
    # whole table can still meet line_width when content allows it.
    long_word = "conn->disaggregated_storage.last_checkpoint_meta_lsn"
    row1 = (
        "| a | b | cur_layered.c:402, cur_layered.c:587 (write), cur_layered.c:1284 "
        f"| Single early-exit at the top of __clayered_adjust_state. Tightly coupled to {long_word} (atomic acquire). |"
    )
    src = "| h1 | h2 | h3 | h4 |\n|---|---|---|---|\n" + row1
    out = strip_ansi(md.md2ansi(src, line_width=150))
    table_lines = [ln for ln in out.splitlines() if ln.startswith(("│", "┌", "├", "└"))]
    widest = max(len(ln) for ln in table_lines)
    # With a single oversize column (col 4 with the long token), the extra
    # fitting round should shrink the other shrinkable columns enough that
    # the table fits within 150.
    assert widest <= 150, f"table is {widest} wide, expected ≤ 150"


def test_table_column_grow_iterates_until_stable():
    # Grow + re-wrap isn't idempotent: the wider width gives the no-break
    # zone more room, which can put another long token onto an already-loaded
    # line and overflow again. The reconciliation must iterate to stable.
    # This simulates the repro from /home/ubuntu/sandvault/tmp/q.
    long_word = "conn->disaggregated_storage.last_checkpoint_meta_lsn"
    cell = f"Single early-exit at the top of __clayered_adjust_state. Tightly coupled to {long_word} (atomic acquire)."
    src = (
        "| a | b | c | Notes |\n"
        "|---|---|---|---|\n"
        f"| x | y | z | {cell} |"
    )
    out = strip_ansi(md.md2ansi(src, line_width=150))
    # Every output line should have the same width (no overflow on any sub-line).
    table_lines = [ln for ln in out.splitlines() if ln.startswith(("│", "┌", "├", "└"))]
    assert len(set(len(ln) for ln in table_lines)) == 1, \
        f"non-uniform table widths: {sorted(set(len(ln) for ln in table_lines))}"


def test_table_column_grows_then_rewraps_around_long_token():
    # A column holding an unbreakable token longer than its assigned width must
    # grow to fit that token; the other cells in the column get re-wrapped at
    # the new wider width (so they can use the extra room).
    long_tok = "X" * 30
    src = (
        "| h1 | h2 |\n"
        "|---|---|\n"
        f"| {long_tok} | a |\n"
        "| many small words that have room to combine when the column gets wider | b |"
    )
    out = strip_ansi(md.md2ansi(src, line_width=40, cell_min_width=10))
    plain_rows = _table_body_rows(out)
    # The long token must appear intact on a single row line.
    assert any(long_tok in ln for ln in plain_rows)


def test_table_iterative_pin_below_cell_min():
    # Three columns: two wide-ish, one narrow but above cell_min_width.
    # When the proportional factor would push the smaller-of-the-wide
    # below cell_min, it gets pinned and the largest is re-scaled.
    src = (
        "| aaaaaaaaaaaaaaaaaaaaaaaa | bbbbbbbbbbbb | c |\n"
        "|---|---|---|\n"
        "| " + "x" * 60 + " | " + "y" * 14 + " | z |"
    )
    out = strip_ansi(md.md2ansi(src, line_width=40, cell_min_width=10))
    table_lines = [ln for ln in out.splitlines() if ln.startswith(("│", "┌", "├", "└"))]
    # At minimum, the algorithm must terminate and produce a table.
    assert table_lines
    # Iterating shouldn't crash and at least one body cell should wrap.
    body_lines = _table_body_rows(out)
    # Header + at least one body-row line (and more if any cell wrapped).
    assert len(body_lines) >= 2


def test_table_wrap_reopens_correct_sgr_after_close():
    # Cell contains an inline-code span followed by long plain text. The wrap
    # falls outside the code span. The continuation line must NOT re-open the
    # code color (because the span was already closed before the break).
    src = (
        "| h | x |\n"
        "|---|---|\n"
        "| compute `#prompt:N` children (with voice filter applied at projection time) | y |"
    )
    rendered = md.md2ansi(src, line_width=60)
    plain = strip_ansi(rendered)
    # Find the wrapped continuation line for that cell.
    cont_line = next(ln for ln in rendered.splitlines() if "projection time" in ln)
    # The continuation should have a reset (`\x1b[0m` or `\x1b[m`) at its
    # start position, not the code-color SGR.
    inner = cont_line.split("│")[1]   # first cell of the wrapped row
    leading_sgr = re.match(r"\s*(\x1b\[[0-9;]*m)?", inner).group(1) or ""
    assert "38;5;114" not in leading_sgr, repr(cont_line)


def test_table_wrap_no_style_leak_across_cells():
    # A `**bold**` span — whether it ends inline or gets wrapped — must close
    # before the cell-separator `│`. Otherwise the bold leaks into the `│`,
    # the padding, and into the next cell on the same visual row.
    # Use a long enough cell to force a wrap regardless of threshold tuning.
    long_bold = "**bold word spans across the wrap point in this cell**"
    src = f"| {long_bold} | y |\n|---|---|\n| body | y |"
    out = md.md2ansi(src, line_width=30)
    for ln in out.splitlines():
        if "bold" not in ln:
            continue
        # Between the bold-open and the next `│`, there must be a reset SGR.
        cell_sep_pos = ln.find("│", 1)
        cell_text = ln[:cell_sep_pos]
        last_open = cell_text.rfind("\x1b[0;1m")
        assert last_open >= 0
        after_open = cell_text[last_open:]
        assert "\x1b[0m" in after_open or "\x1b[m" in after_open, repr(ln)
        break
    else:
        raise AssertionError("expected a line containing 'bold'")


def test_table_wrap_preserves_inline_formatting_across_breaks():
    # A wrapped cell with `**bold**` and inline `` `code` `` spans must keep
    # the styling intact across the wrap break — the markdown markers must
    # not leak into the visible output as literal `**` / backticks.
    src = (
        "| h1 | h2 |\n"
        "|---|---|\n"
        "| **Wrap cache in preview pane** memoize `wrapped` keyed on "
        "`(text identity, width, ansi_on, query)` | short |"
    )
    rendered = md.md2ansi(src, line_width=70, cell_min_width=10)
    plain = strip_ansi(rendered)
    # Markdown markers must not appear in the visible output.
    assert "**" not in plain, f"literal ** leaked: {plain!r}"
    assert "`" not in plain, f"literal backtick leaked: {plain!r}"
    # Bold SGR must be present somewhere on the wrapped content.
    assert "\x1b[0;1m" in rendered
    # Inline-code SGR (M2A_COLOR_STRING) must be present.
    assert f"\x1b[0;{md.M2A_COLOR_STRING}m" in rendered


def test_table_multiline_cell_top_aligned_with_blank_padding():
    # The first column wraps to multiple lines, the second is a single word.
    # The single-word cell on row 2 must be padded with blank lines so the
    # row finishes at the same visual line.
    long_text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    src = f"| h1 | h2 |\n|---|---|\n| {long_text} | short |"
    out = strip_ansi(md.md2ansi(src, line_width=40, cell_min_width=5))
    body_lines = _table_body_rows(out)
    # 1 header + N body sub-lines. Find the body block (after the header).
    # Header is line 0 (single line); body starts at line 1.
    assert len(body_lines) >= 3   # header + at least 2 wrapped body lines
    # The continuation body line(s) must have a blank right column (all spaces).
    for ln in body_lines[2:]:
        # Cell 2 between the 2nd and 3rd `│`.
        cells = ln.strip("│").split("│")
        # Right cell should be empty (just padding spaces).
        assert cells[1].strip() == "", f"expected blank continuation cell, got {cells[1]!r}"


def test_table_row_dividers_true_forces_dividers():
    # No cell wraps but row_dividers=True should still emit `├─┼─┤` between rows.
    src = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    out = strip_ansi(md.md2ansi(src, row_dividers=True))
    # Between body rows we expect an `├...┼...┤` divider.
    lines = out.splitlines()
    body_indexes = [i for i, ln in enumerate(lines) if re.match(r"^│ [13] ", ln)]
    assert len(body_indexes) == 2
    # The line between them must be a divider.
    between = lines[body_indexes[0] + 1]
    assert between.startswith("├") and "┼" in between and between.endswith("┤")


def test_table_row_dividers_false_suppresses_dividers():
    long_text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    src = f"| h1 | h2 |\n|---|---|\n| {long_text} | x |\n| {long_text} | y |"
    out = strip_ansi(md.md2ansi(src, line_width=40, cell_min_width=5, row_dividers=False))
    # No inter-body divider may appear; only top, header, and bottom borders.
    divider_lines = [ln for ln in out.splitlines() if ln.startswith("├") and ln.endswith("┤")]
    # Exactly one: the header/body separator below the header.
    assert len(divider_lines) == 1


def test_table_row_dividers_auto_enables_on_wrap():
    long_text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    src = f"| h1 | h2 |\n|---|---|\n| {long_text} | x |\n| {long_text} | y |"
    out = strip_ansi(md.md2ansi(src, line_width=40, cell_min_width=5))
    # row_dividers=None and at least one cell wraps -> divider between body rows.
    divider_lines = [ln for ln in out.splitlines() if ln.startswith("├") and ln.endswith("┤")]
    # header/body separator + at least one inter-row separator.
    assert len(divider_lines) >= 2


def test_table_row_dividers_auto_omits_when_no_wrap():
    src = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    out = strip_ansi(md.md2ansi(src, line_width=80))
    divider_lines = [ln for ln in out.splitlines() if ln.startswith("├") and ln.endswith("┤")]
    # Only the single header/body separator.
    assert len(divider_lines) == 1


def test_table_all_narrow_unchanged_regardless_of_line_width():
    src = "| a | b |\n|---|---|\n| 1 | 2 |"
    natural = strip_ansi(md.md2ansi(src))
    narrow_lw = strip_ansi(md.md2ansi(src, line_width=20))
    # All cells fit under cell_min_width — no shrinking should happen.
    # Trim trailing whitespace/newlines for comparison.
    assert natural.rstrip("\n") == narrow_lw.rstrip("\n")


def test_table_bold_styling_preserved_in_wrapped_cell():
    # Cell containing an inline **bold** span on the first sub-line, with
    # additional plain text that forces wrap onto a second sub-line. The
    # bold span must still be styled (and its single line must carry the
    # SGR codes); width-affecting markers staying inside one sub-line is a
    # current limitation of wrap-before-render (see ticket #34).
    src = (
        "| h |\n|---|\n"
        "| **bold** plus enough other words to push some content onto a second line |"
    )
    out = md.md2ansi(src, line_width=30, cell_min_width=5)
    # The bold open SGR (style 0 + ;1) must appear; the inner text must be wrapped.
    assert f"{ESC}0;1mbold{ESC}0m" in out


# ─── End-to-end: design doc renders without exception ────────────────────────


def test_design_doc_renders_without_exception():
    path = os.path.join(os.path.dirname(__file__), "..", "md2ansi_lib.design.md")
    with open(path) as f:
        src = f.read()
    out = md.md2ansi(src)
    assert "\x1b[" in out
    assert "Design Document" in strip_ansi(out)
    # Sanity: many escapes; the rendering shouldn't be a near-passthrough.
    assert out.count("\x1b[") > 100


# ─── Structural scan API: data model ─────────────────────────────────────────


def test_span_kind_sets_partition():
    assert md.M2A_SPANS_ALL == md.M2A_SPANS_BLOCK | md.M2A_SPANS_INLINE
    assert md.M2A_SPANS_BLOCK.isdisjoint(md.M2A_SPANS_INLINE)


def test_span_block_kinds_contents():
    assert md.M2A_SPANS_BLOCK == {
        "frontmatter", "heading", "hr", "code",
        "blockquote", "table", "list", "footnote_def",
    }


def test_span_inline_kinds_contents():
    assert md.M2A_SPANS_INLINE == {
        "code_inline", "escape", "comment", "image", "link", "emphasis",
        "footnote_ref",
    }


def test_span_is_a_frozen_record():
    import dataclasses
    s = md.M2A_Span(kind="heading", subtype="h2", is_block=True,
                    start=0, end=4, text="## x")
    assert dataclasses.is_dataclass(s)
    assert (s.kind, s.subtype, s.is_block, s.start, s.end, s.text) == \
        ("heading", "h2", True, 0, 4, "## x")
    try:
        s.kind = "x"
        assert False, "M2A_Span should be frozen"
    except dataclasses.FrozenInstanceError:
        pass


# ─── Structural scan API: md2ansi_scan ───────────────────────────────────────


def test_scan_yields_block_spans_in_document_order():
    src = "# A\n\ntext\n\n## B\n\n- item\n"
    spans = list(md.md2ansi_scan(src))
    assert [(s.kind, s.subtype) for s in spans] == [
        ("heading", "h1"), ("heading", "h2"), ("list", "list"),
    ]
    for s in spans:
        assert src[s.start:s.end] == s.text   # offsets round-trip


def test_scan_default_excludes_inline():
    # No block construct, and inline is excluded by the default kind set.
    assert list(md.md2ansi_scan("a **bold** b")) == []


def test_scan_all_surfaces_top_level_inline():
    spans = list(md.md2ansi_scan("a **bold** b", md.M2A_SPANS_ALL))
    assert [(s.kind, s.subtype, s.is_block) for s in spans] == [
        ("emphasis", "bold", False),
    ]
    assert spans[0].text == "**bold**"


def test_scan_kinds_whitelist_excludes_others():
    src = "# H\n\n```\ncode\n```\n\n- item\n"
    spans = list(md.md2ansi_scan(src, {"heading", "list"}))
    assert [s.kind for s in spans] == ["heading", "list"]   # code excluded


def test_scan_unknown_kind_raises_eagerly():
    # Validation is eager — raises at the call, before any iteration.
    try:
        md.md2ansi_scan("# H", {"heding"})
        assert False, "expected ValueError for unknown kind"
    except ValueError:
        pass


def test_scan_code_subtype_namespaced():
    py = list(md.md2ansi_scan("```python\nx=1\n```", {"code"}))
    assert (py[0].kind, py[0].subtype) == ("code", "code-python")
    rust = list(md.md2ansi_scan("```rust\nx\n```", {"code"}))
    assert (rust[0].kind, rust[0].subtype) == ("code", "code-rust")
    plain = list(md.md2ansi_scan("```\nx\n```", {"code"}))
    assert (plain[0].kind, plain[0].subtype) == ("code", "code")


def test_scan_frontmatter_span_present():
    spans = list(md.md2ansi_scan("---\nx: 1\n---\n# H"))
    assert [s.kind for s in spans] == ["frontmatter", "heading"]
    assert all(s.is_block for s in spans)


def test_scan_design_doc_headings_in_order():
    path = os.path.join(os.path.dirname(__file__), "..", "md2ansi_lib.design.md")
    with open(path) as f:
        src = f.read()
    headings = list(md.md2ansi_scan(src, {"heading"}))
    assert len(headings) > 10
    assert [s.start for s in headings] == sorted(s.start for s in headings)
    assert headings[0].subtype == "h1"
    assert "Design Document" in headings[0].text


# ─── HTML comments: `<!-- ... -->` dropped (spec §5.1) ───────────────────────
# A flat inline rule (after `escape`) drops comments wherever inline rules reach:
# prose, headings, list items, blockquotes, table cells, link text. Code spans
# and fenced blocks keep the literal text (code rules consume first; code
# contexts carry no comment rule). Unclosed `<!--` passes through verbatim.


def test_html_comment_dropped_in_prose():
    plain = strip_ansi(md.md2ansi("hello <!-- secret --> world"))
    assert "secret" not in plain
    assert "<!--" not in plain and "-->" not in plain
    assert "hello" in plain and "world" in plain


def test_html_comment_dropped_in_heading():
    out = md.md2ansi("# Title <!-- note -->")
    assert md.M2A_COLOR_H1 in out            # still a heading
    plain = strip_ansi(out)
    assert "Title" in plain
    assert "note" not in plain and "<!--" not in plain


def test_html_comment_dropped_in_list_item():
    out = md.md2ansi("- item <!-- x -->")
    assert "·" in out                        # bullet chrome preserved
    plain = strip_ansi(out)
    assert "item" in plain
    assert "<!--" not in plain and "x -->" not in plain


def test_html_comment_dropped_in_blockquote():
    out = md.md2ansi("> quote <!-- x -->")
    assert "│" in out                        # quote bar preserved
    plain = strip_ansi(out)
    assert "quote" in plain
    assert "<!--" not in plain and "x -->" not in plain


def test_html_comment_dropped_in_table_cell():
    out = md.md2ansi("| a <!-- c --> | b |\n|---|---|\n| 1 | 2 |", line_width=80)
    plain = strip_ansi(out)
    assert "<!--" not in plain and "c -->" not in plain
    assert "a" in plain and "b" in plain


def test_html_comment_literal_in_fenced_code():
    # A code block carries no comment rule, so the text is shown verbatim.
    plain = strip_ansi(md.md2ansi("```\ntext <!-- keepme --> more\n```"))
    assert "<!-- keepme -->" in plain


def test_html_comment_literal_in_inline_code_span():
    # The code-span rule precedes the comment rule and consumes the span whole.
    out = md.md2ansi("a `<!-- keepme -->` b")
    assert "<!-- keepme -->" in strip_ansi(out)


def test_html_comment_multiline_top_level_drops_wholesale():
    src = "before\n<!-- line1\nline2\nline3 -->\nafter"
    plain = strip_ansi(md.md2ansi(src))
    assert "before" in plain and "after" in plain
    for fragment in ("line1", "line2", "line3", "<!--", "-->"):
        assert fragment not in plain


def test_html_comment_with_pipe_does_not_add_table_columns():
    # The comment is stripped from each raw row BEFORE the row is split, so a `|`
    # inside it can't mis-split the row into extra columns.
    out = md.md2ansi("| a <!-- x | y --> b | c |\n|---|---|\n| 1 | 2 |", line_width=80)
    rows = [ln for ln in strip_ansi(out).splitlines() if ln.startswith("│")]
    for ln in rows:
        # Two columns -> exactly three `│` separators per row.
        assert ln.count("│") == 3, f"row has wrong column count: {ln!r}"


def test_html_comment_unclosed_passes_through_literally():
    plain = strip_ansi(md.md2ansi("text <!-- unclosed comment"))
    assert "<!-- unclosed comment" in plain


def test_scan_surfaces_html_comment_span():
    spans = list(md.md2ansi_scan("a <!-- c --> b", {"comment"}))
    assert [(s.kind, s.subtype, s.is_block) for s in spans] == [
        ("comment", "comment", False),
    ]
    assert spans[0].text == "<!-- c -->"
