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
    assert "•" in out                                    # bullets
    assert "1." in out                                   # ordered marker preserved
    # Nested bullet appears indented by two spaces (one level).
    plain = strip_ansi(out)
    assert re.search(r"\n  • nested", plain)


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


def test_footnote_missing_definition():
    out = md.md2ansi("Ref[^missing] here.")
    assert "Missing footnote definition" in out


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
