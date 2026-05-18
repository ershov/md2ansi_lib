"""md2ansi_lib — single-file, zero-dependency Markdown-to-ANSI library.

See md2ansi_lib.design.md for architecture, naming conventions, and rule tables.
"""

import re
from dataclasses import dataclass, field


# ─── Section 1: SGR color constants ──────────────────────────────────────────

# Universal code-token palette (design §7.3). Bare SGR codes — wrapping in
# `\x1b[...m` is the dispatcher's job.
M2A_COLOR_COMMENT = "38;5;245"   # gray
M2A_COLOR_STRING  = "38;5;114"   # green
M2A_COLOR_NUMBER  = "38;5;220"   # yellow
M2A_COLOR_KEYWORD = "38;5;204"   # pink
M2A_COLOR_BUILTIN = "38;5;147"   # purple


# ─── Section 2: Dataclasses ──────────────────────────────────────────────────

# Design §5.1.

@dataclass(frozen=True, slots=True)
class M2A_Context:
    compiled: re.Pattern
    rules: tuple


@dataclass(slots=True)
class M2A_DocumentState:
    line_width: int = 80
    footnotes: dict = field(default_factory=dict)
    footnote_order: list = field(default_factory=list)


# ─── Section 3: Shared regex fragments ───────────────────────────────────────

# Design §6.2 and §7.2. All fragments are designed to be embedded inside
# re.VERBOSE patterns (whitespace ignored outside character classes; `#` is
# a comment unless escaped).

# String literals — linear, no atomic groups needed. Each char has exactly one
# matching branch: a non-quote non-backslash char OR a backslash + any char.
_M2A_STR_DQ  = r' " (?: [^"\\\n] | \\. )* "  '
_M2A_STR_SQ  = r" ' (?: [^'\\\n] | \\. )* '  "
_M2A_STR_BT  = r" ` (?: [^`\\]   | \\. )* `  "

# Triple-quoted strings — tempered-greedy, no escape handling subtlety.
_M2A_STR_TDQ = r' """ (?: (?!""") [\s\S] )* """ '
_M2A_STR_TSQ = r" ''' (?: (?!''') [\s\S] )* ''' "

# Numbers — hex, binary, octal, int, float, scientific, with `_` digit grouping.
_M2A_NUM = r"""
    \b (?:
        0 [xX] [0-9a-fA-F_]+
      | 0 [bB] [01_]+
      | 0 [oO] [0-7_]+
      | (?: \d [\d_]* )? \. \d [\d_]* (?:[eE][+-]?\d+)?
      | \d [\d_]* (?:[eE][+-]?\d+)?
    ) \b
"""

# Block-start lookahead — substituted into every cross-line inline rule's
# soft-newline branch so inline matching stops at block boundaries.
_M2A_BLOCK_START_AHEAD = r"""
    [ \t]* (?:
        \#
      | >
      | \|
      | `{3,}
      | ~{3,}
      | [-*+][ \t]
      | \d+\.[ \t]
      | $
    )
"""


# ─── Section 4: Context-building utility ─────────────────────────────────────

# Design §5.3. The placeholder rewrite covers both group definitions (`<`-form)
# and backreferences (`=`-form); the trailing `>` or `)` is left alone since
# we only insert the rulename prefix.
_M2A_PLACEHOLDER_RE = re.compile(r"\(\?P(?P<kind>[<=])\*(?P<suffix>\w*)")


def _m2a_build_context(rules):
    rules = tuple(rules)
    alternatives = []
    for name, pat, _fmt, _recurse in rules:
        def _rewrite(m, _name=name):
            suffix = m.group("suffix") or "inner"
            return f"(?P{m.group('kind')}{_name}_{suffix}"
        rewritten = _M2A_PLACEHOLDER_RE.sub(_rewrite, pat)
        alternatives.append(f"(?P<{name}>{rewritten})")
    combined = "|".join(alternatives) if alternatives else r"(?!)"
    compiled = re.compile(combined, re.VERBOSE | re.MULTILINE | re.DOTALL)
    return M2A_Context(compiled=compiled, rules=rules)


# ─── Section 5: Callable formatters ──────────────────────────────────────────


# ─── Section 6: Rule tables ──────────────────────────────────────────────────


# ─── Section 7: Compiled contexts ────────────────────────────────────────────


# ─── Section 8: Internal _md2ansi() and replace dispatcher ───────────────────

# Design §5.4.

def _md2ansi(text, current_style, context, state):
    def _m2a_replace(m):
        groups = m.groupdict()
        for name, _pat, fmt, recurse in context.rules:
            if groups.get(name) is None:
                continue
            match fmt:
                case str() as sgr:
                    inner = groups.get(f"{name}_inner")
                    new_style = f"{current_style};{sgr}"
                    if recurse is not None and inner is not None:
                        inner = _md2ansi(inner, new_style, recurse, state)
                    elif inner is None:
                        inner = m.group(0)
                    return f"\x1b[{new_style}m{inner}\x1b[{current_style}m"
                case _ as func:
                    return func(m, current_style, context, state)
        return m.group(0)
    return context.compiled.sub(_m2a_replace, text)


# ─── Section 9: Public md2ansi() entry point ─────────────────────────────────

# Design §5.5. Footnote rendering is wired in once `_m2a_render_footnotes` and
# `M2A_CONTEXT_MD` exist (Phase 5).

def md2ansi(text, current_style="0", line_width=80):
    """Convert Markdown text to ANSI-colored output."""
    state = M2A_DocumentState(line_width=line_width)
    out = _md2ansi(text, current_style, M2A_CONTEXT_MD, state)
    if state.footnote_order:
        out += _m2a_render_footnotes(state, current_style)
    return out
