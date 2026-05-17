# Source Directive Protocol

This reference explains the `<<source: path:start-end>>` directives that
concept pages embed. Loaded when the host LLM encounters a directive it
hasn't seen before, when debugging why a query is loading too much, or
when writing a new concept page.

## What a directive looks like

Inside concept pages (Markdown), three forms:

```
<<source: src/auth/jwt.py:42-67>>      Range — preferred form
<<source: src/auth/jwt.py:42>>          Single line
<<source: src/auth/jwt.py>>             Whole file — discouraged (lint warns)
```

Place directives inline with the prose:

> The `validate_jwt` function at `<<source: src/auth/jwt.py:42-67>>`
> rejects expired tokens via a constant-time comparison against the
> server's clock.

## What the host LLM does with them

**Default:** ignore them. Most query paths just need the synthesized
concept content; directives are a fallback for "show me the code."

**When the user asks for verbatim code, exact line numbers, or wants to
copy/modify the cited source:**

1. Find the matching directive in the loaded concept page.
2. Use your file-read tool with `offset=start, limit=(end - start + 1)`
   to load **only** the cited line range. Do NOT read the whole file.
3. Quote the code in your reply.

That's it. The directive grammar is a contract that lets you skip
loading code into context until you actually need it.

## Why this matters

Without directives, concept pages tend to grow code blocks (so the LLM
has the code in context even if no one asks for it) or stay vague (so
the user has to ask follow-ups). Neither is ideal. Directives let the
concept stay synthesis-focused while still being precise enough that
verbatim retrieval is one targeted read away.

Token math, typical query:

- **Without directives:** concept page (~1500 tokens) often includes
  inline code blocks (~500 tokens), all loaded whether needed or not.
- **With directives:** concept page (~1000 tokens) plus, *if the user
  asks for code,* ~150-300 tokens for the one cited range.

For the 80%+ of queries that never need verbatim code, the savings are
real and compounding.

## Subset invariant

Every directive's `path` must appear in the parent concept's
`touches_sources` list. The script enforces this via lint rule
**STRUCT-08** — orphan directives are an error, not a warning, because
they break the incremental-update guarantee (if a source contributes to
a concept but isn't in `touches_sources`, the concept won't refresh when
that source changes).

## Range validation

`compile.py lint` reads each referenced file's current line count and
flags directives that point outside the file. **STRUCT-08** also covers
this case.

## Refresh-time propagation

When a concept refreshes because one of its `touches_sources` files
changed:

1. The script re-extracts that file's signatures (synchronously).
2. For each directive that pointed into the changed file, it looks up
   the symbol by name and computes the new line range.
3. It includes a `directive_updates` field in the `concept_refresh` job
   payload:
   ```json
   {
     "job": "concept_refresh",
     "concept_id": "auth-flow",
     "current_path": ".repokb/concepts/auth-flow.md",
     "summaries_to_reread": ["..."],
     "directive_updates": {
       "src/auth/jwt.py:validate_jwt": "42-71",
       "src/auth/jwt.py:refresh_token": "85-103"
     }
   }
   ```
4. The host LLM refreshes the concept and updates each directive's
   range in place. **You don't have to re-discover line numbers — the
   script already did.** Your job is to validate that the surrounding
   prose still makes sense, not to re-grep the file.

## When NOT to use directives

- For prose/docs files (Markdown, RST). The whole file is small;
  directives don't earn their keep.
- For tiny code files (< 30 lines). Just cite the file path.
- When the concept needs to compare or contrast two regions. A directive
  per region works, but consider whether the concept itself should be
  split.

## Audit log (optional)

If `config.audit_directives: true`, the host LLM appends a line to
`.repokb/log.md` each time it resolves a directive:

```
2026-05-17T14:23Z  resolve  src/auth/jwt.py:42-67  (26 lines)
2026-05-17T14:23Z  resolve  src/auth/jwt.py        (whole file — flagged)
```

Run `compile.py inspect --directive-stats` to see ratios. A high
whole-file-load rate suggests the concepts should add more granular
directives, or the LLM (some smaller models in particular) needs more
emphatic protocol reminders.
