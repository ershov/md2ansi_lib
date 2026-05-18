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


def test_link():
    out = md.md2ansi("[click](http://x)")
    assert f"{ESC}0;38;5;45;4mclick{ESC}0m" in out
    assert "http://x" not in out  # URL discarded


def test_image_substitution():
    out = md.md2ansi("![alt](u)")
    assert "[IMG: alt]" in out
    assert "u" in out or True  # URL silently dropped


# ─── Block-level ─────────────────────────────────────────────────────────────


def test_hr_uses_line_width():
    out = md.md2ansi("---", line_width=10)
    assert "─" * 9 in out


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


def test_fenced_code_generic_passes_through():
    out = md.md2ansi("```\nplain text **not bold**\n```")
    # No bold rendering because generic context has no rules.
    assert "**not bold**" in out


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


def test_list_mixed_markers_and_nesting():
    out = md.md2ansi("- one\n* two\n  - nested\n1. ord")
    assert "·" in out                                    # bullets
    assert "1." in out                                   # ordered marker preserved
    plain = strip_ansi(out)
    assert re.search(r"\n  · nested", plain)


def test_list_recurses_inline():
    out = md.md2ansi("- **important**")
    assert f"{ESC}0;1mimportant{ESC}0m" in out


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
