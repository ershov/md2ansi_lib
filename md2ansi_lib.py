#!/usr/bin/env python3

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

# Sentinel meaning "recurse into the same context the rule fired in" — used so
# rules can self-recurse without a circular reference at definition time. The
# dispatcher resolves it to the live context.
_M2A_RECURSE_SELF = object()


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

# These reference M2A_CONTEXT_MD and _md2ansi which are defined later in the
# file. Forward references resolve at call time — fine for function bodies.

_M2A_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _m2a_fired_rule(m, context):
    """Return the name of the rule whose outer named group matched."""
    for name, _pat, _fmt, _recurse in context.rules:
        if m.group(name) is not None:
            return name
    return None


def _m2a_visible_len(s):
    """Length of s with ANSI escapes stripped — used for width calculations."""
    return len(_M2A_ANSI_ESCAPE_RE.sub("", s))


def _m2a_fmt_hr(m, current_style, context, state):
    bar = "─" * max(1, state.line_width - 1)
    return f"\x1b[{current_style}m{bar}\x1b[{current_style}m"


def _m2a_fmt_inline_code(m, current_style, context, state):
    text = m.group(0).strip("`")
    return f"\x1b[{current_style};{M2A_COLOR_STRING}m{text}\x1b[{current_style}m"


def _m2a_fmt_image(m, current_style, context, state):
    name = _m2a_fired_rule(m, context)
    alt = m.group(f"{name}_alt") or ""
    return f"\x1b[{current_style};3;38;5;245m[IMG: {alt}]\x1b[{current_style}m"


def _m2a_fmt_blockquote(m, current_style, context, state):
    text = m.group(0)
    stripped = "\n".join(re.sub(r"^>[ \t]?", "", ln) for ln in text.split("\n"))
    inner = _md2ansi(stripped, current_style, M2A_CONTEXT_MD_INLINE, state)
    bar = f"\x1b[{current_style};38;5;245m│\x1b[{current_style}m "
    return "\n".join(bar + ln for ln in inner.split("\n"))


def _m2a_fmt_table(m, current_style, context, state):
    raw_rows = []
    for ln in m.group(0).strip("\n").split("\n"):
        s = ln.strip()
        if not s.startswith("|"):
            continue
        # `| a | b |` → ['', ' a ', ' b ', ''] → strip outer empties.
        parts = [c.strip() for c in s.strip("|").split("|")]
        raw_rows.append(parts)
    if len(raw_rows) < 1:
        return m.group(0)
    header = raw_rows[0]
    # Detect separator row (e.g. `| --- | :--: |`); skip if present.
    body_start = 1
    if len(raw_rows) >= 2 and all(re.fullmatch(r":?-{2,}:?", c) for c in raw_rows[1]):
        body_start = 2
    body = raw_rows[body_start:]
    n_cols = len(header)

    def pad(row):
        return list(row[:n_cols]) + [""] * max(0, n_cols - len(row))

    header = pad(header)
    body = [pad(r) for r in body]
    rendered_header = [_md2ansi(c, current_style, M2A_CONTEXT_MD_INLINE, state) for c in header]
    rendered_body = [[_md2ansi(c, current_style, M2A_CONTEXT_MD_INLINE, state) for c in r] for r in body]
    widths = [
        max(
            _m2a_visible_len(rendered_header[i]),
            *(_m2a_visible_len(r[i]) for r in rendered_body),
            1,
        )
        for i in range(n_cols)
    ]

    def render_row(cells):
        parts = []
        for i, c in enumerate(cells):
            pad_n = widths[i] - _m2a_visible_len(c)
            parts.append(f" {c}{' ' * pad_n} ")
        return "│" + "│".join(parts) + "│"

    def border(left, mid, right):
        return left + mid.join("─" * (widths[i] + 2) for i in range(n_cols)) + right

    out_lines = [border("┌", "┬", "┐"), render_row(rendered_header), border("├", "┼", "┤")]
    out_lines.extend(render_row(r) for r in rendered_body)
    out_lines.append(border("└", "┴", "┘"))
    return "\n".join(out_lines)


def _m2a_fmt_list(m, current_style, context, state):
    out_lines = []
    for ln in m.group(0).split("\n"):
        match = re.match(r"^([ \t]*)([-*+]|\d+\.)[ \t]+(.*)$", ln)
        if match:
            indent, marker, content = match.groups()
            level = len(indent.expandtabs(4)) // 2
            bullet = "•" if marker in ("-", "*", "+") else marker
            styled = f"\x1b[{current_style};1m{bullet}\x1b[{current_style}m"
            rendered = _md2ansi(content, current_style, M2A_CONTEXT_MD_INLINE, state)
            out_lines.append(f"{'  ' * level}{styled} {rendered}")
        else:
            out_lines.append(ln)
    return "\n".join(out_lines)


def _m2a_fmt_footnote_def(m, current_style, context, state):
    name = _m2a_fired_rule(m, context)
    fid = m.group(f"{name}_id")
    text = m.group(f"{name}_text")
    # Collapse continuation lines (per the multi-line pattern).
    text = re.sub(r"\n[ \t]+", " ", text).strip()
    state.footnotes[fid] = text
    return ""


def _m2a_fmt_footnote_ref(m, current_style, context, state):
    name = _m2a_fired_rule(m, context)
    fid = m.group(f"{name}_id")
    if fid not in state.footnote_order:
        state.footnote_order.append(fid)
    return f"\x1b[{current_style};38;5;226m[^{fid}]\x1b[{current_style}m"


def _m2a_render_footnotes(state, current_style):
    if not state.footnote_order:
        return ""
    out = ["", f"\x1b[{current_style};1mFootnotes:\x1b[{current_style}m"]
    for fid in state.footnote_order:
        text = state.footnotes.get(fid, "Missing footnote definition")
        out.append(
            f"  \x1b[{current_style};38;5;226m[^{fid}]\x1b[{current_style}m {text}"
        )
    return "\n".join(out) + "\n"


def _m2a_fmt_code(m, current_style, context, state, code_context):
    name = _m2a_fired_rule(m, context)
    body = m.group(f"{name}_body")
    rendered = _md2ansi(body, current_style, code_context, state)
    # Subtle frame: dim corners around the block, body keeps its own coloring.
    bar = "─" * 40
    top = f"\x1b[{current_style};38;5;239m┌{bar}\x1b[{current_style}m"
    bot = f"\x1b[{current_style};38;5;239m└{bar}\x1b[{current_style}m"
    return f"{top}\n{rendered}\n{bot}"


# ─── Section 6: Rule tables ──────────────────────────────────────────────────

# Each rule is a 4-tuple: (name, pattern, fmt, recurse) — see design §5.1.

# Python keyword & builtin lists per design §7.4. `type` appears in both lists;
# rule order ensures keyword wins.
_M2A_PY_KEYWORDS = (
    "False|None|True|and|as|assert|async|await|break|case|class|continue|def|del|"
    "elif|else|except|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|"
    "not|or|pass|raise|return|try|type|while|with|yield"
)
_M2A_PY_BUILTINS = (
    "abs|aiter|all|anext|any|ascii|bin|bool|breakpoint|bytearray|bytes|callable|"
    "chr|classmethod|compile|complex|delattr|dict|dir|divmod|enumerate|eval|exec|"
    "filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|"
    "int|isinstance|issubclass|iter|len|list|locals|map|max|memoryview|min|next|"
    "object|oct|open|ord|pow|print|property|range|repr|reversed|round|set|setattr|"
    "slice|sorted|staticmethod|str|sum|super|tuple|type|vars|zip|__import__"
)

# Python string with optional prefix: r/R, b/B, u/U, f/F, plus 2-char combos
# (rb, br, fr, rf, ...). The prefix is anchored at a word boundary so it can't
# attach to the tail of an identifier (`foor"x"` keeps `r` as part of `foor`,
# only `"x"` is matched). Empty prefix is allowed via the outer `?`.
# Each fragment is wrapped in its own `(?:...)` so its internal alternation
# (e.g. `[^"\\\n] | \\.`) cannot interact with the outer `|` chain.
# Triple-quoted alternatives come first so `"""..."""` never matches as `""` + DQ.
# TODO: highlight {…} interpolation inside f-strings (design §7.2 deferred extension).
_M2A_PY_STRING = rf"""
    (?: \b [rRbBuUfF]{{1,2}} )?
    (?:
        (?: {_M2A_STR_TDQ} )
      | (?: {_M2A_STR_TSQ} )
      | (?: {_M2A_STR_DQ}  )
      | (?: {_M2A_STR_SQ}  )
    )
"""

_M2A_RULES_CODE_PYTHON = (
    # Use [^\n] not . because re.DOTALL is set globally; design §6.1.
    ("py_comment",    r"\#[^\n]*",                                    M2A_COLOR_COMMENT, None),
    ("py_string",     _M2A_PY_STRING,                                 M2A_COLOR_STRING,  None),
    ("py_number",     _M2A_NUM,                                       M2A_COLOR_NUMBER,  None),
    ("py_keyword",    rf"\b(?:{_M2A_PY_KEYWORDS})\b",                 M2A_COLOR_KEYWORD, None),
    ("py_builtin",    rf"\b(?:{_M2A_PY_BUILTINS})\b",                 M2A_COLOR_BUILTIN, None),
)

# Bash keyword & builtin lists per design §7.5.
_M2A_SH_KEYWORDS = (
    "if|then|else|elif|fi|case|esac|for|while|until|do|done|in|function|time|"
    "select|break|continue|return|declare|readonly|local|export|set|unset|shift|"
    "exit|trap"
)
_M2A_SH_BUILTINS = (
    "echo|printf|read|cd|pwd|pushd|popd|mkdir|rmdir|rm|cp|mv|ln|ls|cat|grep|sed|"
    "awk|find|test|source|eval|exec|ulimit|umask|wait|kill|sleep"
)

# TODO: highlight $VAR / ${...} interpolation inside double-quoted strings.
_M2A_RULES_CODE_BASH = (
    # `sh_comment` requires preceding `^` or whitespace so `$#`, `$?`, etc. aren't
    # misread as comments. The preceding-character check is a non-capturing lookbehind
    # alternative since `\s` is variable-width.
    ("sh_comment",   r"(?:^|(?<=\s))\#[^\n]*",                       M2A_COLOR_COMMENT, None),
    ("sh_string_dq", _M2A_STR_DQ,                                   M2A_COLOR_STRING,  None),
    ("sh_string_sq", _M2A_STR_SQ,                                   M2A_COLOR_STRING,  None),
    ("sh_number",    _M2A_NUM,                                      M2A_COLOR_NUMBER,  None),
    ("sh_keyword",   rf"\b(?:{_M2A_SH_KEYWORDS})\b",                M2A_COLOR_KEYWORD, None),
    ("sh_builtin",   rf"\b(?:{_M2A_SH_BUILTINS})\b",                M2A_COLOR_BUILTIN, None),
)

# JavaScript keyword & builtin lists per design §7.6.
_M2A_JS_KEYWORDS = (
    "break|case|catch|class|const|continue|debugger|default|delete|do|else|export|"
    "extends|false|finally|for|function|if|import|in|instanceof|new|null|return|"
    "super|switch|this|throw|true|try|typeof|var|void|while|with|yield|let|static|"
    "await|async|of"
)
_M2A_JS_BUILTINS = (
    "Array|Boolean|Date|Error|Function|JSON|Math|Number|Object|RegExp|String|"
    "Symbol|Map|Set|Promise|console|document|window|fetch|setTimeout|setInterval|"
    "clearTimeout|clearInterval|globalThis|undefined|NaN|Infinity"
)

# TODO: highlight ${...} interpolation inside template literals.
_M2A_RULES_CODE_JAVASCRIPT = (
    ("js_comment_line",  r"//[^\n]*",                                M2A_COLOR_COMMENT, None),
    ("js_comment_block", r"/\*(?:(?!\*/)[\s\S])*\*/",                M2A_COLOR_COMMENT, None),
    ("js_string_dq",     _M2A_STR_DQ,                                M2A_COLOR_STRING,  None),
    ("js_string_sq",     _M2A_STR_SQ,                                M2A_COLOR_STRING,  None),
    ("js_string_bt",     _M2A_STR_BT,                                M2A_COLOR_STRING,  None),
    ("js_number",        _M2A_NUM,                                   M2A_COLOR_NUMBER,  None),
    ("js_keyword",       rf"\b(?:{_M2A_JS_KEYWORDS})\b",             M2A_COLOR_KEYWORD, None),
    ("js_builtin",       rf"\b(?:{_M2A_JS_BUILTINS})\b",             M2A_COLOR_BUILTIN, None),
)

# Generic: no rules — fenced block content passes through unchanged.
_M2A_RULES_CODE_GENERIC = ()


# ─── Section 7: Compiled contexts ────────────────────────────────────────────

M2A_CONTEXT_CODE_PYTHON     = _m2a_build_context(_M2A_RULES_CODE_PYTHON)
M2A_CONTEXT_CODE_BASH       = _m2a_build_context(_M2A_RULES_CODE_BASH)
M2A_CONTEXT_CODE_JAVASCRIPT = _m2a_build_context(_M2A_RULES_CODE_JAVASCRIPT)
M2A_CONTEXT_CODE_GENERIC    = _m2a_build_context(_M2A_RULES_CODE_GENERIC)


# ─── Section 6 (cont.): Markdown rule table ──────────────────────────────────

# Inline patterns embed _M2A_BLOCK_START_AHEAD via f-string substitution so the
# soft-newline branch stops at block boundaries (design §6.2).
_BSA = _M2A_BLOCK_START_AHEAD

# Headings — exact-count `#` followed by space ensures mutual exclusion.
_MD_H1 = r"^ \# [ \t]+ (?P<*> [^\n]+ ) $"
_MD_H2 = r"^ \#{2} [ \t]+ (?P<*> [^\n]+ ) $"
_MD_H3 = r"^ \#{3} [ \t]+ (?P<*> [^\n]+ ) $"
_MD_H4 = r"^ \#{4} [ \t]+ (?P<*> [^\n]+ ) $"
_MD_H5 = r"^ \#{5} [ \t]+ (?P<*> [^\n]+ ) $"
_MD_H6 = r"^ \#{6} [ \t]+ (?P<*> [^\n]+ ) $"

_MD_HR = r"^ (?: -{3,} | ={3,} | _{3,} ) [ \t]* $"

# Fenced code blocks — tempered-greedy body so each char has one matching branch.
_MD_CODE_PY = r"""
    ^ [ \t]* ``` [ \t]* python [ \t]* \n
    (?P<*body> (?: (?! ^ [ \t]* ``` [ \t]* $ ) [\s\S] )* )
    ^ [ \t]* ``` [ \t]* $
"""
_MD_CODE_BASH = r"""
    ^ [ \t]* ``` [ \t]* (?:bash|sh) [ \t]* \n
    (?P<*body> (?: (?! ^ [ \t]* ``` [ \t]* $ ) [\s\S] )* )
    ^ [ \t]* ``` [ \t]* $
"""
_MD_CODE_JS = r"""
    ^ [ \t]* ``` [ \t]* (?:javascript|js) [ \t]* \n
    (?P<*body> (?: (?! ^ [ \t]* ``` [ \t]* $ ) [\s\S] )* )
    ^ [ \t]* ``` [ \t]* $
"""
_MD_CODE_GEN = r"""
    ^ [ \t]* (?:```|~~~) \w* [ \t]* \n
    (?P<*body> (?: (?! ^ [ \t]* (?:```|~~~) [ \t]* $ ) [\s\S] )* )
    ^ [ \t]* (?:```|~~~) [ \t]* $
"""

_MD_BLOCKQUOTE = r"^ > [ \t]? [^\n]* (?: \n > [ \t]? [^\n]* )*"

_MD_TABLE = r"^ [ \t]* \| [^\n]* (?: \n [ \t]* \| [^\n]* )*"

_MD_LIST = r"""
    ^ [ \t]* (?: [-*+] | \d+\. ) [ \t]+ [^\n]*
    (?: \n [ \t]* (?: [-*+] | \d+\. ) [ \t]+ [^\n]* )*
"""

_MD_FOOTNOTE_DEF = r"""
    ^ \[ \^ (?P<*id> [^\]\n]+ ) \] : [ \t]+
    (?P<*text> [^\n]+ (?: \n [ \t]+ [^\n]+ )* )
"""

_MD_FOOTNOTE_REF = r" \[ \^ (?P<*id> [^\]\n]+ ) \] "

_MD_CODE_INLINE = r" ` (?P<*> [^`\n]+ ) ` "

_MD_IMAGE = r" ! \[ (?P<*alt> [^\]\n]* ) \] \( (?P<*url> [^)\n]* ) \) "

_MD_LINK = rf"""
    (?<!!) \[ (?P<*>
        (?: [^\]\n] | \n (?! {_BSA} ) )+
    ) \] \( (?P<*url> [^)\n]* ) \)
"""

_MD_BOLDITALIC = rf"""
    \*\*\* (?P<*>
        (?: [^*\n] | \*(?!\*\*) | \n (?! {_BSA} ) )+
    ) \*\*\*
"""

_MD_BOLD_UNDER = rf"""
    \*\*_ (?P<*>
        (?: [^_\n] | \n (?! {_BSA} ) )+
    ) _\*\*
"""

_MD_UNDER_BOLD = rf"""
    _\*\* (?P<*>
        (?: [^*\n] | \*(?!\*) | \n (?! {_BSA} ) )+
    ) \*\*_
"""

_MD_BOLD = rf"""
    \*\* (?P<*>
        (?: [^*\n] | \*(?!\*) | \n (?! {_BSA} ) )+
    ) \*\*
"""

_MD_STRIKE = rf"""
    ~~ (?P<*>
        (?: [^~\n] | ~(?!~) | \n (?! {_BSA} ) )+
    ) ~~
"""

_MD_ITALIC = rf"""
    (?<!\*) \* (?P<*>
        (?: [^*\n] | \n (?! {_BSA} ) )+
    ) \* (?!\*)
"""

# Lambdas binding the code context for each language-specific code block.
def _m2a_code_lambda(code_ctx):
    return lambda m, cs, ctx, st: _m2a_fmt_code(m, cs, ctx, st, code_ctx)

# Inline rules — used to build M2A_CONTEXT_MD_INLINE (where _M2A_RECURSE_SELF
# resolves to INLINE itself), and reused inside _M2A_RULES_MD after rebinding
# the sentinel to the now-built INLINE context. Block-level matches recurse
# into INLINE so heading/quote/cell text never re-triggers block rules
# (otherwise "1. Goals" inside `## 1. Goals` would render as a list).
_M2A_RULES_INLINE_RAW = (
    ("code_inline",   _MD_CODE_INLINE,  _m2a_fmt_inline_code,  None),
    ("image",         _MD_IMAGE,        _m2a_fmt_image,        None),
    ("link",          _MD_LINK,         "38;5;45;4",           _M2A_RECURSE_SELF),
    ("bolditalic",    _MD_BOLDITALIC,   "1;3",                 _M2A_RECURSE_SELF),
    ("bold_under",    _MD_BOLD_UNDER,   "1;3",                 _M2A_RECURSE_SELF),
    ("under_bold",    _MD_UNDER_BOLD,   "1;3",                 _M2A_RECURSE_SELF),
    ("bold",          _MD_BOLD,         "1",                   _M2A_RECURSE_SELF),
    ("strike",        _MD_STRIKE,       "9",                   _M2A_RECURSE_SELF),
    ("italic",        _MD_ITALIC,       "3",                   _M2A_RECURSE_SELF),
    ("footnote_ref",  _MD_FOOTNOTE_REF, _m2a_fmt_footnote_ref, None),
)
M2A_CONTEXT_MD_INLINE = _m2a_build_context(_M2A_RULES_INLINE_RAW)

# Rebind sentinel to INLINE for the full MD rule table.
_M2A_RULES_INLINE_IN_MD = tuple(
    (name, pat, fmt, M2A_CONTEXT_MD_INLINE if recurse is _M2A_RECURSE_SELF else recurse)
    for name, pat, fmt, recurse in _M2A_RULES_INLINE_RAW
)

_M2A_RULES_MD = (
    ("h1",            _MD_H1,           "38;5;226",                                   M2A_CONTEXT_MD_INLINE),
    ("h2",            _MD_H2,           "38;5;214",                                   M2A_CONTEXT_MD_INLINE),
    ("h3",            _MD_H3,           "38;5;118",                                   M2A_CONTEXT_MD_INLINE),
    ("h4",            _MD_H4,           "38;5;21",                                    M2A_CONTEXT_MD_INLINE),
    ("h5",            _MD_H5,           "38;5;93",                                    M2A_CONTEXT_MD_INLINE),
    ("h6",            _MD_H6,           "38;5;239",                                   M2A_CONTEXT_MD_INLINE),
    ("hr",            _MD_HR,           _m2a_fmt_hr,                                  None),
    ("code_python",   _MD_CODE_PY,      _m2a_code_lambda(M2A_CONTEXT_CODE_PYTHON),    None),
    ("code_bash",     _MD_CODE_BASH,    _m2a_code_lambda(M2A_CONTEXT_CODE_BASH),      None),
    ("code_js",       _MD_CODE_JS,      _m2a_code_lambda(M2A_CONTEXT_CODE_JAVASCRIPT),None),
    ("code_generic",  _MD_CODE_GEN,     _m2a_code_lambda(M2A_CONTEXT_CODE_GENERIC),   None),
    ("blockquote",    _MD_BLOCKQUOTE,   _m2a_fmt_blockquote,                          None),
    ("table",         _MD_TABLE,        _m2a_fmt_table,                               None),
    ("list",          _MD_LIST,         _m2a_fmt_list,                                None),
    ("footnote_def",  _MD_FOOTNOTE_DEF, _m2a_fmt_footnote_def,                        None),
) + _M2A_RULES_INLINE_IN_MD

M2A_CONTEXT_MD = _m2a_build_context(_M2A_RULES_MD)


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
                    actual_recurse = context if recurse is _M2A_RECURSE_SELF else recurse
                    if actual_recurse is not None and inner is not None:
                        inner = _md2ansi(inner, new_style, actual_recurse, state)
                    elif inner is None:
                        inner = m.group(0)
                    open_sgr = f"\x1b[{new_style}m"
                    # Re-emit open SGR after each interior newline so every line
                    # of a multi-line span (e.g. triple-quoted strings, fenced
                    # blocks) is self-styled — survives pagers/pipelines that
                    # don't carry SGR state across line breaks.
                    if "\n" in inner:
                        inner = inner.replace("\n", f"\n{open_sgr}")
                    return f"{open_sgr}{inner}\x1b[{current_style}m"
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


if __name__ == "__main__":
    import sys
    paths = sys.argv[1:]
    if paths:
        for path in paths:
            with open(path) as f:
                sys.stdout.write(md2ansi(f.read()))
    else:
        sys.stdout.write(md2ansi(sys.stdin.read()))
