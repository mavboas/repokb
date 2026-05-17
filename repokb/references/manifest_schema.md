# MANIFEST.json Schema

The MANIFEST is the index. Treat it as the **only thing always in context**. Everything else is loaded on demand. Keep it small, keep it accurate.

## Full schema (v2)

```json
{
  "version": 2,
  "root": "/absolute/path/to/repo",
  "created_at": "2026-05-01T10:00:00Z",
  "updated_at": "2026-05-16T14:00:00Z",
  "host_tool": "claude",
  "adapters_emitted_at": "2026-05-16T14:01:00Z",
  "canonical_skill_sha256": "abc123...",
  "model_used": "claude-opus-4-7",
  "config": {
    "include_globs": ["**/*"],
    "exclude_globs": ["node_modules/**", ".git/**", "dist/**"],
    "ingest_binary_docs": true,
    "max_concept_tokens": 1500,
    "max_summary_tokens": 400,
    "max_concepts": 80,
    "signature_extraction": {
      "python": "ast",
      "javascript": "regex",
      "typescript": "regex",
      "go": "regex",
      "rust": "regex",
      "*": false
    },
    "audit_directives": false
  },
  "stats": {
    "sources": 142,
    "summaries": 142,
    "concepts": 18,
    "stale_concepts": 0,
    "total_size_bytes": 2847291,
    "signature_defer_count": 3,
    "signature_defer_rate": 0.03
  },
  "sources": [
    {
      "path": "src/auth/login.py",
      "sha256": "a3f8b2...",
      "sig_sha256": "b9e7c1...",
      "signature_source": "ast",
      "signature_file": "signatures/src__auth__login.py.md",
      "bytes": 4821,
      "mtime": "2026-05-15T09:23:11Z",
      "summary": "summaries/src__auth__login.py.md",
      "tags": ["auth", "session", "jwt"],
      "type": "py",
      "language": "python"
    }
  ],
  "concepts": [
    {
      "id": "auth-flow",
      "file": "concepts/auth-flow.md",
      "topics": [
        "authentication",
        "JWT validation",
        "OAuth callback handling",
        "session lifecycle"
      ],
      "touches_sources": [
        "src/auth/login.py",
        "src/auth/oauth.py",
        "src/middleware/jwt.py",
        "docs/auth.md"
      ],
      "source_directives": [
        {"path": "src/auth/login.py", "start": 42, "end": 67},
        {"path": "src/auth/oauth.py", "start": 18, "end": 30}
      ],
      "related_concepts": ["error-handling", "data-model"],
      "tokens_est": 1180,
      "stale": false,
      "last_synthesized": "2026-05-16T14:00:00Z",
      "gaps": []
    }
  ],
  "renames_log": [
    {"from": "src/old_name.py", "to": "src/new_name.py", "at": "2026-05-14T11:00:00Z"}
  ]
}
```

## v1 → v2 changes

| Where | New field | Default for migrated v1 | Purpose |
|---|---|---|---|
| Top-level | `host_tool` | `"claude"` | Records which tool initialized the KB |
| Top-level | `adapters_emitted_at` | `null` | Set by `emit-adapters`; powers STRUCT-07 |
| Top-level | `canonical_skill_sha256` | `null` | Stamp for drift detection |
| `config` | `signature_extraction` | `{python: ast, javascript: regex, ...}` | Per-language extractor selection |
| `config` | `audit_directives` | `false` | Opt-in logging of `<<source:>>` resolutions |
| `stats` | `signature_defer_count` | `0` | Number of files where LLM deferred to source |
| `stats` | `signature_defer_rate` | `0.0` | Powers PERF-04 |
| `sources[i]` | `sig_sha256` | `null` (populated lazily) | Body-only-edit skip |
| `sources[i]` | `signature_source` | `null` | `"ast" \| "regex" \| null` |
| `sources[i]` | `signature_file` | `null` | Path to the skeleton (relative to `.repokb/`) |
| `sources[i]` | `language` | inferred from `type` | For dispatch into `signature_extraction` |
| `concepts[i]` | `source_directives` | `[]` (populated on next refresh) | MANIFEST mirror for lint |

Migrate via `python repokb/scripts/compile.py migrate --root .`. The migration is in-place, lossless, and does not re-summarize.

## Field-by-field rules

### Top level

- `version` — bump when this schema changes. Migration scripts live in `scripts/migrate.py`.
- `root` — absolute path. Used to detect when the KB has been moved (warn user).
- `model_used` — record which Claude version compiled the KB. Helps debug regressions when re-running with a different model.

### `config`

The interview answers from `init`, persisted so `update` doesn't need to ask again. Editing this by hand is fine, but changes to globs require a re-walk (`update` does this automatically).

### `sources[]`

- `path` — relative to `root`, forward slashes even on Windows.
- `sha256` — primary identity. Used for diffing and rename detection.
- `tags` — **max 5**, enforced by script. Should be domain tags ("auth", "deployment"), not file-type tags ("python", "yaml" — that's `type`).
- `summary` — relative to `.repokb/`. Naming convention: replace `/` with `__` and append `.md`.

### `concepts[]`

This is the routing surface. Quality here directly determines query efficiency.

- `id` — kebab-case, unique, stable. Used in wikilinks like `[[auth-flow]]`. **Never rename** after creation — wikilinks and `related_concepts` references will break. If a concept needs a fundamentally new identity, create a new one and deprecate the old.
- `topics` — **3-8 phrases** describing what questions this concept can answer. These are what Claude reads to decide which concept to load. Be specific: "JWT validation in middleware" beats "auth stuff".
- `touches_sources` — every source that contributed to this concept's synthesis. Powers staleness cascade. Must be exhaustive — if a source contributes but isn't listed, edits to it won't refresh the concept.
- `related_concepts` — concepts that are likely to be co-loaded for adjacent questions. Helps Claude decide when one concept isn't enough.
- `tokens_est` — rough token count of the concept file. Used by `lint` to enforce the 1500 budget.
- `stale` — set by `update` when any `touches_sources` file changed. Cleared by `concept_refresh`.
- `gaps` — array of `{description, since}` for known unresolved questions in this concept. Surfaces in `lint` and helps targeted future ingestion.

## Size budget enforcement

The script aborts a write if the resulting MANIFEST would exceed 3000 tokens (approximate, measured by `len(json) / 4`). When that triggers:

1. Most likely cause: too many sources (~500+). Suggested fix: exclude generated files, vendor dirs, test fixtures
2. Less likely: tags or topics ballooned. Script will print which sources have the longest entries

Never compress MANIFEST by removing fields — every field is load-bearing. Compress by reducing the source set or sharpening tags.

## Reading MANIFEST efficiently

In a query context, you generally need:
- `stats` (one line — gives you scale)
- `concepts[]` (full list — this is the routing menu, ~20-50 entries × ~150 tokens each)
- `sources[]` only if a concept's `touches_sources` requires it for citation

Most queries should not need to read individual `sources[]` entries at all — the `touches_sources` paths inside concepts are enough to know where to point the user for verbatim code.
