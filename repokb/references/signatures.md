# Signature Extraction

This reference is loaded when running `extract-signatures`, when a
`summarize_signature` job appears in the queue, or when debugging why a
file is/isn't getting AST-skeleton treatment.

## Why signatures matter

For code files, most of the "what does this do" information lives in:
- Module-level docstring
- Function/method signatures (name + args + return type)
- Function/method docstrings
- Class hierarchy

That information is **deterministically extractable**. There is no need to
spend LLM tokens reading the whole file to ask "what's in this file" — a
parser knows. The LLM's value-add is narrower: explain the *intent* and
the *non-obvious decisions*, which it can do given the skeleton alone.

For a typical Python file this saves roughly 70% of the Phase 1 token
cost, with the same downstream concept quality.

## Three-tier extractor priority

Per file extension, the script tries:

1. **AST** — language-specific, full fidelity. Python via stdlib `ast`.
2. **Regex** — coarse but zero-dep. JS, TS, Go, Rust.
3. **LLM** — fallback: the host LLM reads the whole source (the legacy
   `summarize` job path).

Selection is config-driven:

```yaml
signature_extraction:
  python: ast        # tier 1
  javascript: regex  # tier 2
  typescript: regex  # tier 2
  go: regex          # tier 2
  rust: regex        # tier 2
  "*": false         # everything else → LLM fallback
```

Set any language to `false` to force LLM summarize for that language.

## The summarize_signature job

When the script identifies a file whose language has an extractor enabled,
it emits this job shape (instead of the legacy `summarize` job):

```json
{
  "job": "summarize_signature",
  "source_path": "src/auth/login.py",
  "out_path": ".repokb/summaries/src__auth__login.py.md",
  "signature_path": ".repokb/signatures/src__auth__login.py.md",
  "sha256": "<source hash>",
  "sig_sha256": "<skeleton hash>"
}
```

The host LLM reads **only the signature file** (~200-500 tokens) and
writes the summary with just two enrichment sections:

```markdown
---
source: src/auth/login.py
sha256: <sha>
type: python
signature_source: ast
tags: [auth, session]
---

# Purpose
One sentence on what this file does in the system.

# Notable decisions / gotchas
Brief notes on non-obvious choices, TODO/HACK markers, performance
considerations, security-sensitive sections. Cite by line range.
```

The skeleton already contains the symbol list — there's no need to repeat it.

## When to read the source after all

The skeleton may include `<<unclear: reason>>` markers next to specific
symbols. The host LLM should read only those line ranges (via its
file-read tool with offset+limit) — never the whole file.

Reasons the extractor emits:

| Reason | Trigger |
|---|---|
| `low-docstring-coverage` | function has no docstring AND body > 50 lines |
| `high-complexity` | cyclomatic complexity > 10 (count of if/for/while/try/and/or/comprehension) |
| `dynamic-construct` | uses `eval`, `exec`, or `getattr(x, "literal")` |
| `decorator-opaque` | any decorator outside the safe set (`property`, `staticmethod`, `classmethod`, `abstractmethod`, `cached_property`, `dataclass`) |
| `user-tagged` | the source contains `# REPOKB: explain` near the symbol |

## Escape hatches

### File-level: full LLM summary

If signature-only is fundamentally wrong for a file (e.g., a 300-line
procedural script), tag the file:

```python
# REPOKB: full-summary
```

The extractor sets `full_summary_requested=True` and the script emits a
legacy `summarize` job instead, so the LLM reads the whole source.

### Symbol-level: defer-to-source

The LLM can decide *during synthesis* that the skeleton is insufficient
and emit a result like:

```json
{
  "job_id": "...",
  "status": "deferred",
  "defer_to_source": true,
  "reason": "function body diverges substantially from its signature"
}
```

The script re-queues that file as a regular `summarize` job. Defer events
are tracked in MANIFEST `stats.signature_defer_rate`.

## Quality monitoring

`compile.py lint` PERF-04 warns when `signature_defer_rate > 30%` — that's
a signal that AST extraction isn't paying off for this codebase, and the
user should consider turning it off for the affected language.

## The big efficiency win: body-only edits

Each source has a `sig_sha256` field (hash of the extracted skeleton, not
the file). When a Python file is modified, `update` compares:

- `sha256` differs (file changed)
- `sig_sha256` unchanged (signature didn't change — only the body did)

→ The script **skips the summarize_signature job entirely**. The existing
summary is still accurate because Purpose and Notable Decisions don't
hinge on function body content the LLM never saw.

This is invisible to the user and produces zero LLM cost for the common
case of "tweak a function body."
