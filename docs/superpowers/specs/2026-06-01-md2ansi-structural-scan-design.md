# md2ansi_lib — Structural Scan API + Frontmatter Support

**Date:** 2026-06-01
**Status:** Approved design, pre-implementation
**Branch:** `md2ansi-structural-scan`

## 1. Motivation

`md2ansi_lib` renders Markdown to ANSI via a single-pass `re.sub` transform
(`_md2ansi` → `_m2a_replace`). It already compiles every block + inline rule
into one regex (`M2A_CONTEXT_MD.compiled`) and walks the document with it — but
the structural information (what construct matched, where it starts/ends) lives
only transiently inside the substitution callback and is discarded.

The `browse-md` recipe wants exactly that structure (heading/list offsets for a
TOC tree) and today **hand-copies this library's block grammar** to re-derive
it (its `_RULES` / `_PARSER_RE` / `_LIST_ITEM_RE` are copies of `md2ansi_lib`'s
`_MD_H1..\_MD_LIST` and `_m2a_fmt_list`'s line regex). This adds a public,
non-rendering "scan" view of the matches the engine already produces, so
consumers stop duplicating the grammar.

Two deliverables:

1. **`md2ansi_scan`** — a generator yielding `M2A_Span` records for top-level
   matches, filtered by kind.
2. **Frontmatter support** — a new block rule so a leading `---…---` YAML block
   renders as a framed "Frontmatter" box (instead of today's HR + parsed body +
   HR, which mangles YAML and can leak inline spans past the closing `---`), and
   appears in the scan stream as `kind="frontmatter"`.

## 2. Public API

### 2.1 `M2A_Span`

```python
@dataclass(frozen=True, slots=True)
class M2A_Span:
    kind: str       # broad category (see table)
    subtype: str    # always set; falls back to `kind` when there's no finer detail
    is_block: bool  # True = block construct, False = inline
    start: int      # character offset into the input text (str index, not bytes)
    end: int        # one past the match; text[start:end] == .text
    text: str       # the matched source slice (m.group(0))
```

Offsets are Python `str` indices over the **raw, unwrapped** input (the scan
never runs `_m2a_wrap_source`), so `text[span.start:span.end] == span.text`.

### 2.2 kind / subtype / is_block mapping

Rules not listed fall back to `kind = subtype = <rule name>`. Every built-in
`subtype` maps to exactly one `kind`, so `subtype`-only matching is
unambiguous. (Caveat: code fence tags are free-form author text, so they are
namespaced under `code-` to avoid colliding with other subtypes; a pathological
` ```bold ` yields `subtype="code-bold"`, still unique.)

| rule(s) | `kind` | `subtype` | `is_block` |
|---|---|---|---|
| `frontmatter` | `frontmatter` | `frontmatter` | True |
| `h1`…`h6` | `heading` | `h1`…`h6` | True |
| `hr` | `hr` | `hr` | True |
| `code_python` | `code` | `code-python` | True |
| `code_bash` | `code` | `code-bash` | True |
| `code_js` | `code` | `code-javascript` | True |
| `code_generic` | `code` | `code-<tag>` if tag else `code` | True |
| `blockquote` | `blockquote` | `blockquote` | True |
| `table` | `table` | `table` | True |
| `list` | `list` | `list` | True |
| `footnote_def` | `footnote_def` | `footnote_def` | True |
| `code_inline2`, `code_inline` | `code_inline` | `code_inline` | False |
| `escape` | `escape` | `escape` | False |
| `image` | `image` | `image` | False |
| `link` | `link` | `link` | False |
| `bolditalic`, `bold_under`, `under_bold` | `emphasis` | `bolditalic` | False |
| `bold` | `emphasis` | `bold` | False |
| `strike` | `emphasis` | `strike` | False |
| `italic` | `emphasis` | `italic` | False |
| `footnote_ref` | `footnote_ref` | `footnote_ref` | False |

`list` has no `ul`/`ol` subtype: a list rule matches a whole consecutive block
that can mix markers, and the per-item `ul`/`ol` distinction only emerges from
fanning/recursion (out of scope; that's `browse-md`'s own `_walk_list`).

A broad `kind` never straddles the block/inline divide — that's why
`footnote_def` (block) and `footnote_ref` (inline) stay distinct kinds rather
than grouping under `footnote`: filtering is by `kind`, so a shared kind would
leak an inline ref into a block-only scan.

Implementation: a small static dict holds only the rules whose `kind`/`subtype`
differ from the fallback (headings, the four `code_*`, the emphasis group);
everything else derives from the rule name. `is_block` is computed as "rule name
not in the inline rule-name set" (`_M2A_RULES_INLINE_RAW`). For `code_generic`,
`subtype` reads the captured fence-tag group.

### 2.3 `md2ansi_scan`

```python
def md2ansi_scan(text, kinds=M2A_SPANS_BLOCK):
    """Yield M2A_Span for top-level matches whose `kind` is in `kinds`, in
    document order. Non-recursive. Raises ValueError if `kinds` contains a
    name not in M2A_SPANS_ALL."""
```

- Validates `set(kinds) <= M2A_SPANS_ALL`; raises `ValueError` listing the
  unknown kind(s). Fail-fast typo guard for caller-composed sets, and surfaces
  any future kind rename loudly instead of silently matching nothing.
- Runs `M2A_CONTEXT_MD.compiled.finditer(text)` — the same regex/engine/order
  the renderer uses, so the scan can't drift from what gets rendered.
- For each match, identifies the outer rule via the same "first non-None outer
  group wins" loop as `_m2a_replace`, maps to `(kind, subtype, is_block)`,
  filters by `kind in kinds`, and yields `M2A_Span(...)`.
- Single `finditer` pass is **non-recursive**: it yields every block span plus
  any inline match at top level (paragraph text). Inline markup *inside* a
  heading/quote/table/list-item stays masked within that block's span and is
  not separately reported. Complete for block structure; partial for inline (by
  design — see recursion, out of scope).

### 2.4 Kind-set constants

```python
M2A_SPANS_BLOCK  = frozenset({'frontmatter','heading','hr','code',
                              'blockquote','table','list','footnote_def'})
M2A_SPANS_INLINE = frozenset({'code_inline','escape','image','link',
                              'emphasis','footnote_ref'})
M2A_SPANS_ALL    = M2A_SPANS_BLOCK | M2A_SPANS_INLINE   # universe + validation set
```

All derived from the rule tables (mapped through the kind table, partitioned by
the inline rule-name set) — nothing hand-maintained beyond the small kind dict.
`kinds` is an ordinary set of kind strings, composed by set arithmetic:

```python
md2ansi_scan(src)                                  # block-only (default)
md2ansi_scan(src, M2A_SPANS_BLOCK - {'frontmatter'})
md2ansi_scan(src, {'heading', 'list'})             # e.g. browse-md TOC
md2ansi_scan(src, M2A_SPANS_ALL)                   # include top-level inline
```

Operators are frozenset's `|` `-` `&` (not `+`). No per-kind constants and no
`StrEnum` (would proliferate symbols; `StrEnum` is 3.11+ while the lib targets
3.10+ and favors plain string constants). `recursive=` remains the one deferred
orthogonal axis.

## 3. Frontmatter support (engine change)

### 3.1 Rule

```python
_MD_FRONTMATTER = r"""
    \A (?P<*indent>) --- [ \t]* \n
    (?P<*body>
        (?: ^ (?! --- [ \t]* $ ) (?! [ \t]* \# ) (?! [ \t]* $ ) [^\n]* \n )*
    )
    ^ --- [ \t]* $
"""
```

- `\A`-anchored: matches only at document start, never mid-document.
- Body is a run of lines that are each non-empty, non-comment (`#…`), and not
  the closing fence; the first blank line, `#` comment, or `---` ends it.
  Requiring a tight block keeps real markdown (blank lines / `#` headings) from
  being mistaken for frontmatter when a doc opens with a `---` thematic break.
  Linear — each char matched once.
- Closing `---` ends at `$`; it does NOT consume its trailing newline (like
  code fences), so the framed box doesn't merge with the following line.
- Empty `(?P<*indent>)` group so the existing `_m2a_fmt_code` framing code
  (which reads `{name}_indent`) works unchanged with an empty indent.

Added as the **first** entry in `_M2A_RULES_MD`. It must precede `hr` (both can
match a leading `---`; Python alternation is leftmost-first). Headings are
unaffected (a `---` line is not a heading).

### 3.2 Rendering

Reuse `_m2a_fmt_code`'s framing by adding an optional `label` parameter
(default keeps today's `"Code[: lang]"` logic; frontmatter passes
`label="Frontmatter"`), bound via a lambda to the **generic / no-highlight**
code context so YAML content passes through verbatim (not parsed as Markdown,
not syntax-highlighted). Output is a framed box titled `Frontmatter`, visually
consistent with code blocks.

### 3.3 Wrap pre-pass

`_m2a_wrap_source` runs before rendering when `line_width > 0` and is
frontmatter-unaware — it could word-wrap a long YAML line. Teach it to skip a
leading frontmatter block, exactly as it already skips fenced code. (No effect
on the scanner, which never wraps.)

### 3.4 Behavior change + escape hatch

- A document of shape `\A---\n…\n---` now renders as one Frontmatter box
  instead of HR + parsed body + HR. Documented as a new entry in the design
  doc's §10.2 "intrinsic exceptions to minimal intrusion" list, alongside
  HR / table / footnotes.
- A lone leading `---` with **no** closing `---` fails the frontmatter match
  and falls through to `hr` (graceful; preserves current behavior). The two
  existing HR tests use exactly this shape and are unaffected.
- Escape hatch (renderer): build a frontmatter-less grammar from exported
  building blocks and call the advanced entry point —
  `_md2ansi(text, "0", _m2a_build_context(tuple(r for r in _M2A_RULES_MD if r[0] != 'frontmatter')), M2A_DocumentState(...))`.
  Documented as a recipe; promoted to a constant only if it earns its keep
  (avoids compiling a second large regex at import for a rare case).
- Escape hatch (scanner): omit `'frontmatter'` from `kinds` (the underlying
  match still masks the YAML, which is the desired behavior).

## 4. Testing plan

Pure-function tests in the existing style (feed Markdown, assert on output /
yielded spans):

- **Scan:** document order; `text[start:end] == text` round-trip; `is_block`
  correctness; default = block-only (no inline leaks); `kinds={'heading','list'}`
  whitelist; `M2A_SPANS_ALL` surfaces top-level inline; unknown kind raises
  `ValueError`; code subtype namespacing (`code-python`, generic `code-<tag>`,
  tagless `code`); emphasis grouping; frontmatter span present.
- **Frontmatter render:** `\A---\n…\n---` → framed "Frontmatter" box, body
  verbatim (not Markdown-parsed); lone `---` still HR; mid-document `---` still
  HR; long YAML line not wrapped under `line_width>0`.
- **Regression:** existing suite stays green (the two HR tests confirmed
  unaffected).

## 5. Out of scope

- `recursive=` scanning (inline-inside-blocks with rebased absolute offsets;
  per-item `ul`/`ol` fanning).
- The `browse-md` refactor that consumes `md2ansi_scan` (separate follow-up).
- Promoting the no-frontmatter context to an eager constant.

## 6. Downstream

`browse-md` imports the **vendored** `browse-tui/recipes/md2ansi.py` (a
paste-copy of this library), so the new symbols must be re-vendored there for
`browse-md` to use them — same paste-portability discipline that already keeps
the two in sync. Re-vendoring + the `browse-md` `_parse` collapse are tracked
separately from this library change.
```
