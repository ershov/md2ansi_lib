# md2ansi_lib — Flat HTML Tags & Entities — Design

Support a small set of **flat** (non-nesting) HTML constructs and HTML entities in
`md2ansi_lib`, with zero changes to the dispatch engine. See `md2ansi_lib.design.md`
for the engine architecture this builds on.

## 1. Scope

**In scope** (all flat — match a token, replace with content or nothing; `recurse=None`):

1. **Comments** — `<!-- … -->` → dropped (no output).
2. **Line breaks** — `<br>`, `<BR>`, `<br/>`, `<br />` (case-insensitive, optional self-close) → a hard line break.
3. **Horizontal rules** — `<hr>` and variants → a horizontal rule, sized to its container.
4. **Entities** — `&name;`, `&#dec;`, `&#xHEX;` → decoded as inert inline content.

**Out of scope** (deferred): paired / nestable tags (`<i>`, `<b>`, `<em>`, `<strong>`,
`<u>`, `<s>`, `<code>`, `<a href>`, `<img>`, block containers `<ul>/<ol>/<li>/<table>/<pre>/<blockquote>`).
These need tree-structured parsing the flat regex engine does not do.

## 2. Guiding principles

- **HTML is content, never raw control.** An expanded construct must never re-interact
  with Markdown control characters or inject a raw layout character mid-render. `&#42;`
  must not become italic; `&#124;` must not split a table; `&#35;` must not become a
  heading. A construct that *means* a line break (`<br>`, or a newline/CR entity) is
  routed through a **sentinel** so it renders as `\n` in the final output but never
  injects a raw newline that corrupts a table or list during rendering.
- **No raw control characters survive to output.** Every C0 control codepoint is either
  routed to a safe sentinel (line break, non-breaking space) or replaced with `�`
  (U+FFFD). This holds for both source text (input sanitizer, §4) and decoded entities
  (§5.4).
- **Context-free vs. deferred — the key distinction.**
  - *Entities are context-free*: `&amp;` is `&` regardless of where it sits, so they
    resolve **immediately during the inline pass**. This is load-bearing, not
    incidental: resolving inline means block rules already matched the *raw* source
    (no mis-split), and table column widths are measured on the *expanded* text (no
    misalignment). Deferring entities would break both.
  - *`<br>` / `<hr>` / `&nbsp;` are deferred layout instructions*: their realization
    depends on the enclosing block (a `<br>` is a newline in prose but a cell-split
    in a table; an `<hr>` is sized to its container; an `&nbsp;` must survive
    wrapping as glue, then become a space). They emit a sentinel that the layout
    owner or the final pass realizes.
- **Cheapest correct behavior for malformed input.** Unclosed/unknown constructs pass
  through literally — which is automatic: anything not matching a rule is left verbatim.

## 3. Architecture — no engine change

Everything is additive rule tuples plus small handler edits. `_md2ansi`,
`_m2a_build_context`, the placeholder rewrite, and the style stack are untouched.

- **Inline-set rules** added to `_M2A_RULES_INLINE_RAW`, positioned **after `escape`**
  (so a backslash-escaped `\<br>` / `\&amp;` stays literal) and before the emphasis
  rules: `html_comment`, `html_br`, `html_hr_inline`, `html_entity`. By construction
  these are inherited by `M2A_CONTEXT_MD_INLINE`, `M2A_CONTEXT_MD_BLOCKLITE`, and the
  top-level MD table — so they work in prose, headings, table cells, list items,
  blockquotes, and link text.
- **Block rule** `html_hr` added to `_M2A_RULES_MD`, near the existing `hr` rule:
  matches a standalone `<hr>` line and **reuses the existing `_m2a_fmt_hr`** handler
  (full page width).
- **Case-insensitivity** is per-pattern via scoped inline flags `(?i:…)`. The combined
  regex compiles with `VERBOSE | MULTILINE | DOTALL` and **no** global `IGNORECASE`,
  and it is one shared pattern, so a global flag is not an option.

## 4. Sentinel model

The library already uses one internal control-char sentinel, `_M2A_OPAQUE = "\x00"`
(a line that owns its own layout and is exempt from the post-render wrap pass). We add
three more. All four share **plumbing** but keep **distinct semantics/stages**.

| Char | Name | Meaning | Emitted by | Realized |
|------|------|---------|------------|----------|
| `\x00` | `_M2A_OPAQUE` (existing) | line is pre-laid-out | block formatters | final pass strips the marker |
| `\x01` | `_M2A_LINEBREAK` | hard line break | `html_br` (`<br>`); newline/CR entity | table/list/quote split into sub-lines; prose **and heading** → real `\n` |
| `\x02` | `_M2A_RULE` | horizontal rule | `html_hr_inline` (`<hr>` as inline content) | layout owner inserts `─ × container-width`; prose & heading → full-width rule |
| `\x03` | `_M2A_NBSP` | non-breaking space | `&nbsp;` / any entity resolving to U+00A0 | final pass → `" "` (intrinsically non-breaking in between) |

**Shared plumbing (converge here):**

- **One input sanitizer** (top of `md2ansi()`): normalize `\r\n`/`\r` → `\n`, then
  replace every C0 control char except `\t`, `\n`, `\x1b` (ESC) with `�`. The kill
  class is `[\x00-\x08\x0B\x0C\x0E-\x1A\x1C-\x1F]`. This *also* neutralizes any stray
  sentinel char (`\x00`–`\x03`) present in the source, so it can never be mistaken for
  one we emitted. (Scoped to C0 / range 0–31 per spec; ESC is kept so pre-colored
  source survives.)
- **One final-pass sweep** (`_m2a_wrap_rendered`): the single place residual sentinels
  are realized (see §5.2, §5.3, §6).
- **One safety property:** no raw control character ever reaches output — each is routed
  to `\x01` / `\x03` or replaced with `�`. (`\x00` and `\x02` are never produced by
  entity decoding.)

**Why not fully unify entities and sentinels:** the discriminator is *“does realization
depend on enclosing layout?”* Entities: no → resolve now. Sentinels: yes → defer.
Unifying would force entities to defer (losing width-correctness) or sentinels to
resolve early (losing layout context). So: unified mechanics, distinct stages.

## 5. Per-construct specification

### 5.1 Comments — `<!-- … -->`

- **Pattern:** tempered-greedy, multi-line — `<!-- (?: (?! --> ) [\s\S] )* -->`
  (same shape as the existing `js_comment_block` / `c_comment_block`).
- **Handler:** drop — return `""` (precedent: `_m2a_fmt_footnote_def`).
- **Reach:** inline-set rule → dropped in prose, headings, list items, blockquotes,
  cells, link text. Multi-line comments at top level drop wholesale because the rule
  has `recurse=None` and `re.sub` does not rescan the (empty) replacement.
- **Code protection:** the `code_*` / `frontmatter` block rules precede the inline
  rules and consume their whole block, and the code contexts carry no comment rule, so
  a `<!-- … -->` shown inside a code block or `` `code span` `` stays literal.
- **Robustness (decision B):** `_m2a_fmt_table` strips comments from each raw row line
  **before** `_m2a_split_table_row`, so a comment containing `|` cannot mis-split a
  row. (Other block handlers split on line-leading markers, not on in-line structural
  chars, so they need no equivalent.)
- **Unclosed** `<!--` (no `-->`) → no match → passes through literally.

### 5.2 Line breaks — `<br>`

- **Pattern:** `(?i: < br [ \t]* /? > )`.
- **Handler:** emit `_M2A_LINEBREAK` (`\x01`). **Not** a raw `\n` — a raw newline is
  eaten as collapsible whitespace by `_m2a_wrap_ansi_line`, is split on by the
  post-render pass, and corrupts the table box.
- **Realization by container:**
  - **Prose** (non-opaque): final pass splits the line on `\x01` into separate output
    lines (each independently wrapped; continuation = the line’s leading whitespace, so
    the part after a mid-line `<br>` starts at column 0).
  - **Table cell:** `cell_sublines` splits the rendered cell on `\x01` → multi-row cell
    via the existing list-of-sub-lines + `render_row` top-align/padding + row-divider
    machinery (today reached only by width-wrapping; see
    `test_table_multiline_cell_top_aligned_with_blank_padding`).
  - **List item / blockquote:** split on `\x01` → hard break with the correct hang
    indent / `│ ` bar, *before* the block is marked opaque.
  - **Heading** (§5 corner case): the handler converts `\x01 → \n` before color+opaque,
    producing a **multi-line heading**. `_m2a_inject_color` re-emits the heading color
    after each newline and `_m2a_opaque` marks each line, so every line stays colored
    and exempt from wrapping. A multi-line heading is unambiguous precisely because it
    stays color-marked.

### 5.3 Horizontal rules — `<hr>`

Invariant: **`<hr>` always draws a horizontal rule sized to its container** — full page
width at top level / in prose / in a heading, cell width in a table, item-content width
in a list.

- **Block rule `html_hr`:** `^ [ \t]* (?i: < hr [ \t]* /? > ) [ \t]* $` → reuse
  `_m2a_fmt_hr` (full page width, opaque). At top level a standalone `<hr>` line is won
  by this rule because block rules precede the inline rules in the combined alternation
  (and, with leading whitespace, its match also starts further left).
- **Inline rule `html_hr_inline`:** `(?i: < hr [ \t]* /? > )` → emit `_M2A_RULE`
  (`\x02`). Fires for `<hr>` that is *content* inside a table cell, list item, or
  heading (reached via INLINE / BLOCKLITE recursion, where the block rule is absent).
- **Realization of `\x02`:**
  - **Measurement phase** (table fit / wrap): `\x02` is counted as a **double line
    break (`\n\n`)** — i.e. it always occupies one extra sub-line for the rule — and
    contributes **zero** width demand (it fills width, never forces it).
  - **Final layout:** the layout owner replaces each `\x02` slot with `─ × frozen-width`
    (column width in a table; item-content width in a list; `wrap_width − 2` in a
    blockquote).
  - **Prose** (`\x02` that reached the final pass uncontained): emit `─ × line_width`
    on its own line (a mid-prose `<hr>` acts like a block rule).
  - **Heading:** the handler materializes `\x02` as a `─ × (line_width − 1)` line in the
    heading color (split inner on `\x02`, insert the rule line) before color+opaque.

### 5.4 Entities — `&name;` / `&#dec;` / `&#xHEX;`

- **Pattern:** `& (?: \# [0-9]+ | \# [xX] [0-9a-fA-F]+ | [a-zA-Z][a-zA-Z0-9]* ) ;`
  — requires the trailing `;`, so `AT&T` and bare `&` never match (→ literal).
- **Handler `_m2a_fmt_entity`** (decoded **inline**, so it is naturally “after block
  structure, during text formatting”):
  - **Named, known** (in `_M2A_HTML_ENTITIES`) → its character; if that character is
    U+00A0 (`nbsp`) → emit `\x03`.
  - **Named, unknown** → return the match unchanged (**literal pass-through**, per the
    WHATWG standard — browsers do not substitute anything).
  - **Numeric** → codepoint `n` (decimal or hex), then, in order:
    - `n == 0`, surrogate `0xD800–0xDFFF`, or `n > 0x10FFFF` → `�` (U+FFFD).
    - `n == 0x0A` (LF) or `n == 0x0D` (CR) → `\x01` (safe line break; renders as `\n`
      in the final output, splits safely in tables/lists). **Supersedes earlier decision
      A (“map to space”).**
    - `n == 0xA0` → `\x03` (non-breaking space).
    - other control — `n < 0x20`, DEL `0x7F`, or C1 `0x80–0x9F` → `�`. *(We deliberately
      skip the WHATWG Windows-1252 C1 legacy remap; mapping C1 → `�` is simpler and
      consistent with the “no raw control survives” property.)*
    - otherwise → `chr(n)`.
- **Not expanded in code:** inline code spans and fenced blocks are consumed first / use
  contexts without the entity rule, so `` `&amp;` `` and entities in code blocks stay
  literal — correct behavior.
- **Why timing is automatically correct:** every Markdown rule matched the raw source
  where the entity was still `&#…;`, so an entity can never trigger emphasis, a table
  split, or a heading; and table widths are measured on the expanded text.

**Named entity seed set** (~25 common; numeric covers the rest):
`amp lt gt quot apos nbsp copy reg trade mdash ndash hellip bull middot sect para
deg times divide laquo raquo larr rarr uarr darr pound euro cent yen`.

## 6. Handler & module changes (summary)

| Location | Change |
|----------|--------|
| SGR/constants section | add `_M2A_LINEBREAK="\x01"`, `_M2A_RULE="\x02"`, `_M2A_NBSP="\x03"`; `_M2A_HTML_ENTITIES` dict |
| new handlers | `_m2a_fmt_comment` (drop), `_m2a_fmt_br` (→`\x01`), `_m2a_fmt_hr_inline` (→`\x02`), `_m2a_fmt_entity` |
| `_M2A_RULES_INLINE_RAW` | add 4 rules after `escape` |
| `_M2A_RULES_MD` | add `html_hr` block rule near `hr` |
| `_m2a_fmt_heading` | realize `\x01`→`\n` and `\x02`→`─ × (line_width−1)` rule line (heading color) before color+opaque → multi-line heading |
| `_m2a_fmt_table` | strip comments per raw row before split; `cell_sublines` split on `\x01`/`\x02`; `\x02` measured as `\n\n` (zero-width rule sub-line), expand to `─` at render |
| `_m2a_fmt_list` | split item content on `\x01` (hang-indent break) and `\x02` (`─` line at item width) |
| `_m2a_fmt_blockquote` | `\x01`→break (bar per line); `\x02`→`─×(width−2)` line |
| `_m2a_wrap_rendered` | single sentinel sweep: prose `\x01`→line split, `\x02`→full-width rule, `\x03`→`" "`; opaque lines `\x03`→`" "` |
| `md2ansi()` | input sanitizer: normalize CR→`\n`; map C0 controls `[\x00-\x08\x0B\x0C\x0E-\x1A\x1C-\x1F]` → `�` (neutralizes stray sentinels) |
| scan API `_M2A_SPAN_KINDS` | `html_hr`→`("hr","hr")`, `html_comment`→`("comment","comment")`, `html_br`→`("br","br")`, `html_entity`→`("entity","entity")`; broad-kind sets auto-extend |

## 7. Edge cases & documented behavior

- **`<br>` / `<hr>` inside a heading** are *rendered*, not neutralized: the heading
  becomes multi-line / gains a rule line, each line color-marked and opaque. Allowed
  because color-marking keeps a multi-line heading unambiguous.
- **Multi-line comment interleaved into a block** (table/list): the block-grouping
  regex stops at the first non-structural continuation line *before* any handler runs,
  so such a comment is not cleanly absorbed. Inherent to the flat engine (same family
  as “no nested blocks”). Documented, not fixed.
- **Newline / CR entity** behaves like `<br>` (routed through `\x01`): two adjacent
  entities (`&#13;&#10;`) therefore produce two breaks — accepted (HTML does treat them
  as two characters).
- **`&nbsp;` non-breaking guarantee** holds against the library’s own wrapper (`\x03`
  glues into a word token). A downstream pager re-wrapping the final spaces is outside
  our control.
- **Unknown-named / unclosed / bare `&` or `<`** → literal pass-through (by construction).
- **Raw control chars in source** → `�` (except `\t`, `\n`, `\x1b`; `\r`→`\n`).

## 8. Testing plan

Following the existing flat `def test_*` + `strip_ansi` style. New cases:

- **Comments:** dropped in prose / heading / list item / blockquote / table cell;
  preserved literal inside fenced code and inline code span; multi-line top-level drop;
  comment-with-`|` on a table row does not add columns; unclosed `<!--` literal.
- **`<br>`:** prose break; **table cell** break (multi-row cell, top-aligned, dividers);
  **nested list item** break (hang indent preserved); case/`/` variants; heading →
  multi-line (each line still colored + opaque).
- **`<hr>`:** standalone line full width; **inside a table cell** (`─` at column width,
  width measured before materialization); **inside a nested list item** (`─` at item
  width, not full page); mid-prose full-width; inside a heading (colored rule line).
- **Entities — expanded as inert content (no control interaction):**
  `&#42;`→`*` not italic; `&#95;` not emphasis; `&#124;` inside a table cell stays in
  one cell; `&#35;` at line start is not a heading; `&amp;`→`&`; `&amp;amp;`→`&amp;`;
  unknown `&notreal;` literal; `&nbsp;` non-breaking then space; numeric hex `&#x41;`→`A`;
  entity inside `` `code` `` stays literal.
- **Premature-decoding hazards (explicit — point 6):** `&#10;` / `&#13;` (LF/CR) inside
  a **table cell** → safe row split, box intact; inside a **nested list item** → safe
  break; `&#10;` in prose → `\n`; a decoded newline **adjacent to a raw input control
  char** (e.g. source `&#10;` immediately followed by a literal `\x07`) → `\n` + `�`,
  surrounding formatting intact; `&#1;` / `&#7;` / `&#127;` (DEL) / `&#128;` (C1) → `�`;
  `&#0;` and surrogate `&#xD800;` → `�`.

## 9. Out of scope

Paired/nestable tags and structural block HTML, ReDoS wrappers, autolinks
(`<https://…>`), C1-range *input* sanitizing (input is scoped to C0 / 0–31), and the
WHATWG Windows-1252 C1 numeric remap (we map C1 → `�` instead).
