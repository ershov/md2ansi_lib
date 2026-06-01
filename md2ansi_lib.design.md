# md2ansi_lib.py — Design Document

A single-file, zero-dependency Markdown-to-ANSI library, embeddable by verbatim paste.

## 1. Goals

- Convert Markdown to ANSI-colored terminal text in one call.
- Support full markdown surface (inline + block) using a single rules-driven engine.
- No external dependencies. Python 3.10+ (uses `match/case`).
- All identifiers namespace-prefixed (`M2A_*`, `_m2a_*`) so the file can be pasted verbatim into another codebase without collisions.
- Minimally-intrusive output: preserve source shape (newlines, blank lines, indentation) wherever rendering doesn't require structural change.
- Complete rewrite — no shared code, no references to any prior implementation.

## 2. Public API

```python
def md2ansi(text, current_style="0", line_width=80):
    """Convert Markdown text to ANSI-colored output."""
```

Exports (top-level names available after `from md2ansi_lib import *` or paste):

| Symbol | Kind | Purpose |
|---|---|---|
| `md2ansi` | function | Public entry point |
| `_md2ansi` | function | Internal workhorse (advanced use; takes Context + state) |
| `M2A_DocumentState` | dataclass | Mutable per-document state (line_width, footnotes) |
| `M2A_Context` | dataclass | Immutable grammar (compiled regex + rules) |
| `M2A_CONTEXT_MD` | M2A_Context | Markdown grammar |
| `M2A_CONTEXT_CODE_PYTHON` | M2A_Context | Python syntax-highlight grammar |
| `M2A_CONTEXT_CODE_BASH` | M2A_Context | Bash syntax-highlight grammar |
| `M2A_CONTEXT_CODE_JAVASCRIPT` | M2A_Context | JS syntax-highlight grammar |
| `M2A_CONTEXT_CODE_GENERIC` | M2A_Context | Fallback (no highlighting) |
| `M2A_COLOR_*` | str constants | Bare SGR codes (no `\e[...m` wrapping) |

## 3. Naming Conventions

Required so the file can be pasted into other code without symbol clashes.

| Convention | Used for | Example |
|---|---|---|
| `md2ansi` | Public interface functions (full name) | `md2ansi()` |
| `_md2ansi` | Internal counterpart of public function | `_md2ansi()` |
| `M2A_*` (UPPER) | Public constants and dataclasses | `M2A_COLOR_BOLD`, `M2A_DocumentState` |
| `_M2A_*` (UPPER, leading `_`) | Private module-level constants | `_M2A_BLOCK_START_AHEAD`, `_M2A_PLACEHOLDER_RE` |
| `_m2a_*` (lower, leading `_`) | Private functions | `_m2a_build_context`, `_m2a_fmt_table` |

No module-level identifier escapes one of these prefixes.

## 4. Python Style Requirements

- **Python 3.10+** (for `match/case`).
- F-strings for all string formatting.
- `match/case` instead of `if/elif` chains where dispatching on a discriminator.
- `@dataclass` (with `slots=True` where lifetime is short). Note: dataclasses require field annotations as a language feature — those stay.
- Walrus `:=` where it improves readability.
- Type annotations on function signatures are **optional**, not required. Use them where they clarify; skip where they add noise.
- No `from __future__ import annotations` (caller-pasteable; want runtime evaluation behavior consistent across Python versions).

## 5. Architecture

### 5.1 Core data structures

```python
@dataclass(frozen=True, slots=True)
class M2A_Context:
    compiled: re.Pattern    # Combined regex for this grammar
    rules: tuple            # Original rule tuples (for handler dispatch)

@dataclass(slots=True)
class M2A_DocumentState:
    line_width: int = 80
    footnotes: dict = field(default_factory=dict)        # id -> text
    footnote_order: list = field(default_factory=list)   # appearance order
```

Rules are 4-tuples: `(name, pattern, fmt, recurse)` where:
- `name` — str identifier (drives `(?P<name>...)` outer group and `(?P<*...>)` rewrite)
- `pattern` — regex source (`re.VERBOSE` mode)
- `fmt` — either an SGR-codes string (e.g., `"1;3"`) or a callable `(match, current_style, context, state) → str`
- `recurse` — `M2A_Context` to recurse content into, or `None` to leave content as a literal

### 5.2 Style stack

A single string of SGR codes, e.g. `"0;38;5;226;1"`.
- Default `current_style = "0"` — naturally clears formatting.
- Each nesting level appends `;{new_sgr}` to its inherited stack — no conditionals.
- Emitted as `\e[{stack}m` on entry, `\e[{outer_stack}m` on exit.
- The leading `0` in every emission resets prior state, making each escape self-contained — terminals never need to track partial state from us.

Example chain: link containing bold:
- Outer text style: `"0"` → emit `\e[0m`
- Enter link: stack becomes `"0;38;5;45;4"` → emit `\e[0;38;5;45;4m`
- Enter bold inside link: stack becomes `"0;38;5;45;4;1"` → emit `\e[0;38;5;45;4;1m`
- Exit bold: emit `\e[0;38;5;45;4m` (back to link style)
- Exit link: emit `\e[0m`

### 5.3 Rules table → compiled regex

At module load, each `M2A_Context` is built by `_m2a_build_context(rules)`:

1. For each rule `(name, pat, fmt, recurse)`, rewrite the pattern:
   - `(?P<*inner>...)` → `(?P<{name}_inner>...)`
   - `(?P<*foo>...)` → `(?P<{name}_foo>...)`
   - Backreferences `(?P=*foo)` → `(?P={name}_foo)`
2. Wrap each rewritten pattern: `(?P<{name}>{rewritten})` (outer named group for alternative detection).
3. Join alternatives with `|`.
4. Compile with `re.VERBOSE | re.MULTILINE | re.DOTALL`.

Placeholder rewrite is done by a regex over the pattern string:

```python
_M2A_PLACEHOLDER_RE = re.compile(r"\(\?P([<=])\*(\w*)>")
# Group 1: '<' for definition or '=' for backreference
# Group 2: optional suffix (empty → "inner")
```

### 5.4 Substitution handler

`_md2ansi(text, current_style, context, state)`:

```python
def _md2ansi(text, current_style, context, state):
    def _m2a_replace(m):
        for name, _pat, fmt, recurse in context.rules:
            if m.group(name) is None:
                continue
            match fmt:
                case str() as sgr:
                    inner = m.group(f"{name}_inner")
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
```

### 5.5 Public entry point

```python
def md2ansi(text, current_style="0", line_width=80):
    state = M2A_DocumentState(line_width=line_width)
    out = _md2ansi(text, current_style, M2A_CONTEXT_MD, state)
    if state.footnote_order:
        out += _m2a_render_footnotes(state, current_style)
    return out
```

## 6. Regex Patterns

### 6.1 Flags

All compiled with `re.VERBOSE | re.MULTILINE | re.DOTALL`.

VERBOSE-mode gotchas:
- Whitespace outside `[...]` is ignored. Use `[ ]` or `\ ` for a literal space, `\s` for any whitespace.
- `#` starts a comment. Use `\#` for a literal hash (relevant for header patterns).

### 6.2 Block-start lookahead

One constant, substituted into every inline rule's "soft-newline" branch:

```python
_M2A_BLOCK_START_AHEAD = r"""
    [ \t]* (?:                  # optional leading whitespace, then ...
      \#                        # any heading
      | >                       # blockquote
      | \|                      # table
      | `{3,}                   # fenced code (backtick)
      | ~{3,}                   # fenced code (tilde)
      | [-*+][ \t]              # unordered list marker
      | \d+\.[ \t]              # ordered list marker
      | $                       # blank line
    )
"""
```

Each cross-line inline rule contains:

```
| \n (?! {_M2A_BLOCK_START_AHEAD} )
```

as a branch. Built via `.format()` substitution at module load.

### 6.3 No lazy quantifiers

All previously-lazy patterns use **tempered-greedy** with negative lookahead:

```
General form:  open (?: (?! close ) [\s\S] )* close
```

Each character has exactly one matching branch → linear time. Used for fenced code blocks, block comments, triple-quoted docstrings.

## 7. Rule Set

### 7.1 `M2A_CONTEXT_MD` rule order

Block-level rules first (greedy multi-line where applicable), then inline.

| # | Name | Match | fmt | recurse |
|---|---|---|---|---|
| 1 | `h1` | `^\# [text]$` | str `"38;5;226"` | `M2A_CONTEXT_MD` |
| 2 | `h2` | `^\#{2} [text]$` | str `"38;5;214"` | `M2A_CONTEXT_MD` |
| 3 | `h3` | `^\#{3} [text]$` | str `"38;5;118"` | `M2A_CONTEXT_MD` |
| 4 | `h4` | `^\#{4} [text]$` | str `"38;5;21"` | `M2A_CONTEXT_MD` |
| 5 | `h5` | `^\#{5} [text]$` | str `"38;5;93"` | `M2A_CONTEXT_MD` |
| 6 | `h6` | `^\#{6} [text]$` | str `"38;5;239"` | `M2A_CONTEXT_MD` |
| 7 | `hr` | `^(?:-{3,}|={3,}|_{3,})[ \t]*$` | callable `_m2a_fmt_hr` | None |
| 8 | `code_python` | `` ^```python\n...\n```$ `` | lambda → `_m2a_fmt_code(..., M2A_CONTEXT_CODE_PYTHON)` | None |
| 9 | `code_bash` | `` ^```bash\n...\n```$ `` | lambda → `_m2a_fmt_code(..., M2A_CONTEXT_CODE_BASH)` | None |
| 10 | `code_javascript` | `` ^```javascript\n...\n```$ `` | lambda → `_m2a_fmt_code(..., M2A_CONTEXT_CODE_JAVASCRIPT)` | None |
| 11 | `code_generic` | `` ^(```|~~~)\w*\n...\n(```|~~~)$ `` | lambda → `_m2a_fmt_code(..., M2A_CONTEXT_CODE_GENERIC)` | None |
| 12 | `blockquote` | `^> ?[^\n]*(?:\n> ?[^\n]*)*$` | callable `_m2a_fmt_blockquote` | None |
| 13 | `table` | `^[ \t]*\|[^\n]*(?:\n[ \t]*\|[^\n]*)*$` | callable `_m2a_fmt_table` | None |
| 14 | `list` | matches consecutive lines starting with `-`, `*`, `+`, or `\d+\.` (mixable; indent-driven nesting) | callable `_m2a_fmt_list` | None |
| 15 | `footnote_def` | `^\[\^id\]:[ \t]+text(\n[ \t]+text)*$` | callable `_m2a_fmt_footnote_def` (mutates state, returns "") | None |
| 16 | `code_inline` | `` `[^`]+` `` | callable `_m2a_fmt_inline_code` | None |
| 17 | `image` | `!\[alt\]\(url\)` | callable `_m2a_fmt_image` | None |
| 18 | `link` | `\[(?P<*inner>text)\]\((?P<*url>url)\)` | str `"38;5;45;4"` (cyan + underline) | `M2A_CONTEXT_MD` |
| 19 | `bolditalic` | `\*\*\*...\*\*\*` | str `"1;3"` | `M2A_CONTEXT_MD` |
| 20 | `bold_under` | `\*\*_..._\*\*` | str `"1;3"` | `M2A_CONTEXT_MD` |
| 21 | `under_bold` | `_\*\*...\*\*_` | str `"1;3"` | `M2A_CONTEXT_MD` |
| 22 | `bold` | `\*\*...\*\*` | str `"1"` | `M2A_CONTEXT_MD` |
| 23 | `strike` | `~~...~~` | str `"9"` | `M2A_CONTEXT_MD` |
| 24 | `italic` | `(?<!\*)\*...\*(?!\*)` | str `"3"` | `M2A_CONTEXT_MD` |
| 25 | `footnote_ref` | `\[\^id\]` | callable `_m2a_fmt_footnote_ref` (registers + renders) | None |

Order rationale:
- Headings 1–6 are mutually exclusive by construction (`^\#{N} ` requires exact count + space). Order doesn't matter among them.
- Block-level patterns before inline: greedy block matches consume whole blocks before inline rules see fragments.
- Within block: `code_*` before `blockquote`/`list`/`table` (fenced code can contain `|`, `>`, etc.).
- `bolditalic` and underscore variants before `bold` (longer delimiter first).
- `bold` (`**`) before `italic` (`*`) — Python re's alternation is first-match-wins at each position.
- `image` before `link` (`![]()` vs `[]()`).

### Notes on specific rules

**List** — matches all three unordered bullet markers (`-`, `*`, `+`) and numbered markers (`\d+\.`). Markers may be mixed within one list block — the handler renders each item's marker as styled `*` for bullets or the original number for ordered items. Nesting is indent-driven (every 2 spaces = one level).

**Link** — string-fmt because we just want to color the visible text with link style and recurse for nested inline formatting (bold/italic/code inside link text). The URL is captured by `(?P<*url>...)` for pattern correctness but discarded from output. If a future need arises (e.g., OSC 8 hyperlinks), this rule can be promoted to a callable.

**Image** — callable because it substitutes content (`![alt](url)` → `[IMG: alt]`), not just styles it.

### 7.2 Shared regex fragments

To avoid duplicating common token patterns across languages, define module-level constants used in `.format()`-substitution into rule patterns.

```python
# String literals — deliberate escape handling (linear, no atomic groups needed).
# Each character matches exactly one branch: a non-quote non-backslash char,
# OR a backslash followed by any single char (the escape).
_M2A_STR_DQ     = r' " (?: [^"\\\n] | \\. )* "  '   # "double-quoted"
_M2A_STR_SQ     = r" ' (?: [^'\\\n] | \\. )* '  "   # 'single-quoted'
_M2A_STR_BT     = r" ` (?: [^`\\]   | \\. )* `  "   # `backtick` (allows newline)

# Python-only: triple-quoted strings (no escape-handling subtlety; tempered-greedy).
_M2A_STR_TDQ    = r' """ (?: (?!""") [\s\S] )* """ '
_M2A_STR_TSQ    = r" ''' (?: (?!''') [\s\S] )* ''' "

# Numbers — covers hex, binary, octal, integer, float, scientific, with optional
# underscore digit grouping (Python-style; harmless for other langs since `_`
# inside number literals isn't valid syntax there but won't false-match either).
_M2A_NUM = r"""
    \b (?:
        0 [xX] [0-9a-fA-F_]+                          # hex
      | 0 [bB] [01_]+                                 # binary
      | 0 [oO] [0-7_]+                                # python octal
      | (?: \d [\d_]* )? \. \d [\d_]*  (?:[eE][+-]?\d+)?   # float w/ point
      | \d [\d_]*  (?:[eE][+-]?\d+)?                  # int or scientific
    ) \b
"""
```

**Deferred to future:** string-interpolation coloring (Python f-strings, bash `$VAR` / `${...}`). Each language file will have a `# TODO: highlight interpolation inside strings` comment near its string rules so the place to extend is obvious.

### 7.3 Universal code-token colors

A single palette is used across all languages — no per-language color constants. Defined alongside the other SGR constants in Section 1:

```python
M2A_COLOR_COMMENT = "38;5;245"   # gray
M2A_COLOR_STRING  = "38;5;114"   # green
M2A_COLOR_NUMBER  = "38;5;220"   # yellow
M2A_COLOR_KEYWORD = "38;5;204"   # pink
M2A_COLOR_BUILTIN = "38;5;147"   # purple
```

Each language's rule table references these constants directly (not inline SGR strings).

### 7.4 `M2A_CONTEXT_CODE_PYTHON` rules

Each rule is string-fmt (SGR code), no recursion. Order: comments → triple-strings → strings → numbers → keywords → builtins.

| Name | Match | Color |
|---|---|---|
| `py_comment` | `\#.*$` | `M2A_COLOR_COMMENT` |
| `py_string_tdq` | `_M2A_STR_TDQ` | `M2A_COLOR_STRING` |
| `py_string_tsq` | `_M2A_STR_TSQ` | `M2A_COLOR_STRING` |
| `py_string_dq` | `_M2A_STR_DQ` | `M2A_COLOR_STRING` |
| `py_string_sq` | `_M2A_STR_SQ` | `M2A_COLOR_STRING` |
| `py_number` | `_M2A_NUM` | `M2A_COLOR_NUMBER` |
| `py_keyword` | `\b(?:<keywords>)\b` | `M2A_COLOR_KEYWORD` |
| `py_builtin` | `\b(?:<builtins>)\b` | `M2A_COLOR_BUILTIN` |

**Python keywords (modern, 3.13-current):**

```
False None True and as assert async await break case class continue def del
elif else except finally for from global if import in is lambda match nonlocal
not or pass raise return try type while with yield
```

Includes Python 3.10+ soft keywords `match`/`case` and the 3.12 `type` statement.

**Python builtins (modern):**

```
abs aiter all anext any ascii bin bool breakpoint bytearray bytes callable
chr classmethod compile complex delattr dict dir divmod enumerate eval exec
filter float format frozenset getattr globals hasattr hash help hex id input
int isinstance issubclass iter len list locals map max memoryview min next
object oct open ord pow print property range repr reversed round set setattr
slice sorted staticmethod str sum super tuple type vars zip __import__
```

### 7.5 `M2A_CONTEXT_CODE_BASH` rules

| Name | Match | Color |
|---|---|---|
| `sh_comment` | `(?:^\|\s)\#.*$` | `M2A_COLOR_COMMENT` |
| `sh_string_dq` | `_M2A_STR_DQ` | `M2A_COLOR_STRING` |
| `sh_string_sq` | `_M2A_STR_SQ` | `M2A_COLOR_STRING` |
| `sh_number` | `_M2A_NUM` | `M2A_COLOR_NUMBER` |
| `sh_keyword` | `\b(?:if then else elif fi case esac for while until do done in function time select break continue return declare readonly local export set unset shift exit trap)\b` | `M2A_COLOR_KEYWORD` |
| `sh_builtin` | `\b(?:echo printf read cd pwd pushd popd mkdir rmdir rm cp mv ln ls cat grep sed awk find test source eval exec ulimit umask wait kill sleep)\b` | `M2A_COLOR_BUILTIN` |

### 7.6 `M2A_CONTEXT_CODE_JAVASCRIPT` rules

| Name | Match | Color |
|---|---|---|
| `js_comment_line` | `//.*$` | `M2A_COLOR_COMMENT` |
| `js_comment_block` | `/\*(?:(?!\*/)[\s\S])*\*/` | `M2A_COLOR_COMMENT` |
| `js_string_dq` | `_M2A_STR_DQ` | `M2A_COLOR_STRING` |
| `js_string_sq` | `_M2A_STR_SQ` | `M2A_COLOR_STRING` |
| `js_string_bt` | `_M2A_STR_BT` | `M2A_COLOR_STRING` |
| `js_number` | `_M2A_NUM` | `M2A_COLOR_NUMBER` |
| `js_keyword` | `\b(?:break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof new null return super switch this throw true try typeof var void while with yield let static await async of)\b` | `M2A_COLOR_KEYWORD` |
| `js_builtin` | `\b(?:Array Boolean Date Error Function JSON Math Number Object RegExp String Symbol Map Set Promise console document window fetch setTimeout setInterval clearTimeout clearInterval globalThis undefined NaN Infinity)\b` | `M2A_COLOR_BUILTIN` |

### 7.7 `M2A_CONTEXT_CODE_GENERIC`

No rules — fenced block content passes through unchanged, wrapped only in the codeblock color by the fenced-code handler.

## 8. Handler signatures

String fmt: handled by `_m2a_replace` inline (no separate function).

Callable fmt signature:

```python
def _m2a_fmt_foo(m, current_style, context, state):
    """Returns a fully-rendered ANSI-styled string."""
    ...
```

Callable handlers receive:
- `m` — the Match object
- `current_style` — SGR stack inherited from caller
- `context` — the Context this rule fired in
- `state` — DocumentState (mutable — used by footnote handlers; read for `line_width` by HR)

## 9. File layout

```
md2ansi_lib.py
├── module docstring + imports
├── Section 1: SGR constants (M2A_COLOR_*)
├── Section 2: Dataclasses (M2A_Context, M2A_DocumentState)
├── Section 3: Shared regex fragments (_M2A_STR_DQ, _M2A_STR_SQ, _M2A_STR_BT,
│              _M2A_STR_TDQ, _M2A_STR_TSQ, _M2A_NUM, _M2A_BLOCK_START_AHEAD)
├── Section 4: Context-building utility (_m2a_build_context, _M2A_PLACEHOLDER_RE)
├── Section 5: Callable formatters (_m2a_fmt_hr, _m2a_fmt_table, _m2a_fmt_list,
│              _m2a_fmt_blockquote, _m2a_fmt_inline_code, _m2a_fmt_image,
│              _m2a_fmt_footnote_def, _m2a_fmt_footnote_ref, _m2a_fmt_code,
│              _m2a_render_footnotes)
├── Section 6: Rule tables
│              _M2A_RULES_CODE_PYTHON     (defined first — referenced by lambdas
│              _M2A_RULES_CODE_BASH        in _M2A_RULES_MD)
│              _M2A_RULES_CODE_JAVASCRIPT
│              _M2A_RULES_CODE_GENERIC
│              _M2A_RULES_MD
├── Section 7: Compiled contexts (M2A_CONTEXT_CODE_*, M2A_CONTEXT_MD)
├── Section 8: Internal _md2ansi() and replace dispatcher
└── Section 9: Public md2ansi() entry point
```

Estimated total: 500–650 lines (verbose-mode patterns inflate line count but pay back in readability).

## 10. Behavior Notes

### 10.1 Minimal intrusion

- Plain text passes through `re.sub` unchanged. Newlines, blank lines, indentation preserved.
- No paragraph rule, no aggressive reformatting.
- Inline formatting spans soft line breaks; `_M2A_BLOCK_START_AHEAD` stops it at block boundaries.

### 10.2 Intrinsic exceptions to minimal-intrusion

- **HR**: `---` → `─` × `(line_width - 1)`. Inherent.
- **Table**: `| col |` → bordered ASCII table. Inherent.
- **Footnotes section**: appended at document end if any footnote definitions/refs were seen.
- **Frontmatter**: a leading `---`…`---` block (tight: no blank lines or `#` comments) → framed "Frontmatter" box; content passes through verbatim (not parsed as markdown).

### 10.3 Footnote semantics

- `[^id]` (ref): registers `id` in `state.footnote_order` if not present; renders inline as styled `[^id]`.
- `[^id]: text` (def): stores `id → text` in `state.footnotes` (allows continuation lines per markdown spec); produces no output at the definition site.
- After `_md2ansi` completes: if `state.footnote_order` is non-empty, append `Footnotes:` heading + each footnote in appearance order. References without definitions show `Missing footnote definition`.

### 10.4 Error tolerance

Markdown is permissive. Anything not matched by any rule passes through unchanged — including mismatched delimiters, stray asterisks, etc.

## 11. Out of Scope

- ReDoS protection wrappers. All patterns are linear by construction (tempered-greedy, no `*?`).
- File I/O. Library takes string input; caller handles reading.
- Terminal width detection. Caller passes `line_width`.
- CLI argument parsing.
- Signal handling.

A CLI wrapper can be built later that handles those concerns and calls `md2ansi_lib.md2ansi(text, line_width=detected_width)`.

## 12. Open Items (post-implementation)

- `line_width` is accepted but only HR uses it for now. Future: paragraph wrapping, table-cell wrapping.
- Unit tests are needed; suggested to target `md2ansi_lib.md2ansi` directly with markdown fixtures and assert ANSI-output snapshots.
- String-interpolation highlighting (Python f-strings, bash `$VAR` / `${...}`) deferred — placeholder comments in the per-language string rules mark the extension point.
- Performance: verbose patterns + many alternatives in one compiled regex; benchmark after implementation if it becomes a concern.
