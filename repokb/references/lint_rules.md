# Lint Rules

`scripts/compile.py lint` runs structural and health checks. Loaded when the user asks "what's wrong with the KB" or after a noisy update.

## Rules

### STRUCT-01: Stale concept
Concept has `stale: true` in MANIFEST. **Fix:** run `update` to refresh.

### STRUCT-02: Orphan summary
A summary file exists for a source that no concept references. **Fix:** either extend an existing concept's `touches_sources` to include it, or remove it (`compile.py prune-orphan-summary --path X`). Orphans are not always bugs — they can be legitimately marginal files (config samples, examples). The lint reports them but doesn't auto-delete.

### STRUCT-03: Broken wikilink
A concept page contains `[[some-id]]` that doesn't resolve to an existing concept. **Fix:** either fix the link or remove it. Usually caused by deleting a concept without grep-replacing its references.

### STRUCT-04: Concept exceeds token budget
A concept page exceeds `config.max_concept_tokens` (default 1500). **Fix:** split it. Run `compile.py suggest-split --concept X` — the script will propose 2-3 sub-concepts based on which `touches_sources` clusters together within the page.

### STRUCT-05: Concept with single source
A concept references only one source. Likely a misnamed summary. **Fix:** either merge into a broader concept or delete the concept and rely on the summary directly.

### STRUCT-06: Source unreferenced by any concept and untagged as marginal
Source exists with summary, no concept touches it, and it's not in `config.marginal_sources`. **Fix:** decide if it belongs in a concept; if not, mark it marginal so future lints stay quiet.

### KNOW-01: Declared gap
Concept frontmatter contains a `gaps` entry. Surface to user so they can decide whether to fix. Common gaps: "no docs found explaining X", "implementation diverges from docs". Not necessarily a bug — sometimes the gap is real.

### KNOW-02: Suspected contradiction
A concept page contains `<!-- contradiction: ... -->` markers. Surface them so the user can investigate. Claude inserts these during synthesis when two sources disagree (e.g., docs say one thing, code does another).

### KNOW-03: Stale documentation source
A source in `docs/` hasn't been modified in N days (default 180) but adjacent code sources have. Suggests docs are drifting. **Soft warning** — user decides.

### STRUCT-07: Adapter drift
An emitted per-tool instruction file (`CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `.cursor/rules/repokb.mdc`) is out of sync with what the canonical `repokb/SKILL.md` would produce now. Triggered by:
- Hand-edits to the file (outside the sentinel block for sentinel-mode adapters)
- Canonical SKILL.md changed after emit
- Adapter's `CONVENTION_VERSION` advanced

**Fix:** `python repokb/scripts/compile.py emit-adapters --diff-only` to see the drift, then `emit-adapters` to fix.

### STRUCT-08: Orphan or out-of-bounds source directive
A concept page contains `<<source: path:start-end>>` where either:
- `path` is not in the concept's `touches_sources` (orphan)
- the line range exceeds the actual file length

Orphans break the incremental-update guarantee. **Fix:** add the path to `touches_sources` (and re-run `update` so the concept refreshes), or remove the directive.

### STRUCT-09: Code-block-heavy concept
A concept page has more than 5 fenced code blocks. Suggests the concept is becoming a copy of the source rather than a synthesis. **Fix:** replace code blocks with prose-with-citation via `<<source:>>` directives. See `references/source_directives.md`.

### PERF-01: MANIFEST size approaching limit
MANIFEST > 80% of the 3000 token budget. **Fix:** see `manifest_schema.md` size enforcement section.

### PERF-02: Too many concepts
`stats.concepts > config.max_concepts` (default 80). **Fix:** introduce nested topic indexing (see `scaling.md`) or merge fine-grained concepts.

### PERF-03: Concept fanout too wide
A concept touches > 20 sources. Suggests the topic is too broad and routing precision suffers. **Fix:** split.

### PERF-04: Signature defer rate too high
`stats.signature_defer_rate > 30%` — the host LLM is frequently asking for full-source summaries instead of using the AST skeleton. This usually means AST extraction isn't paying off for this codebase. **Fix:** set `signature_extraction.<language>: false` for the affected language in `config.yaml`, or tag individual problematic files with `# REPOKB: full-summary`.

## Reporting format

Lint emits a single Markdown block grouped by rule, with severity (`error`, `warning`, `info`). Errors should be addressed before relying on the KB for new queries; warnings are advisory.

```
## STRUCT-01 (error) — 2 stale concepts
- auth-flow (stale since src/auth/oauth.py changed at 2026-05-15)
- data-pipeline (stale since src/etl/load.py changed at 2026-05-15)

## KNOW-02 (warning) — 1 contradiction
- concepts/deploy.md:42 — "docs say port 8080, code uses 8000"
```

When surfacing lint to the user, prioritize: errors first, then KNOW-* warnings (substantive content issues), then STRUCT/PERF warnings (structural hygiene).
