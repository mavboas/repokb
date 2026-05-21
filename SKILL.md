---
name: repokb
description: Compile and query a persistent, token-efficient knowledge base for a code repository or technical project. Activate when the user asks to "index", "compile", "ingest", "understand", "remember", or "build a knowledge base of" a repo, codebase, docs folder, ADRs, RFCs, or runbooks — especially when the same project will be revisited across sessions. Also activate on the phrases "OpenKB", "compiled wiki", "concept pages", "cross-document synthesis", or when the user complains about re-reading the same files every session. Maintains a `.repokb/` directory (MANIFEST + concept pages + signatures) so future queries load a tiny index instead of raw source files.
---

# RepoKB — Token-Efficient Knowledge Base for Code Projects

RepoKB compiles a repo's knowledge once into a layered wiki on disk (`.repokb/`), then keeps it current via content-hashed incremental updates. Future queries load `MANIFEST.json` + 1–3 synthesized concept pages instead of raw source files.

## When to use

Activate when the user:

- Asks to **learn / index / compile / ingest** a repo, codebase, docs folder, or technical project
- Wants to **answer questions** about a codebase without re-reading files each session
- Mentions **OpenKB**, **PageIndex**, **compiled wiki**, **concept pages**, or **`.repokb/`**
- Asks to **update** or **refresh** the KB after code changes
- Asks to find **contradictions, gaps, or stale info** across project docs

Do **not** activate for one-off questions about files already in context, general web research, or projects without persistent state.

## Layout

```
.repokb/
├── MANIFEST.json      Layer 1 — always loaded (~1-3K tokens)
├── concepts/          Layer 2 — load 1-3 per query
├── signatures/        AST/regex skeletons for code files
├── summaries/         Layer 3a — rarely loaded
├── sources/           Layer 3b — almost never loaded
├── log.md             Append-only operations history
└── config.yaml        Skill configuration
```

Routing is by topic match against the MANIFEST — no embeddings, no ANN. This works because concepts are coarse-grained (10–50 per repo).

## Workflow

### `init` — bootstrap

When no `.repokb/` exists and the user says "compile a KB" / "index this project":

```bash
python repokb/scripts/compile.py init --root . --config-from-interview
```

Briefly ask the user: include/exclude paths beyond `.gitignore`, whether to ingest binary docs (PDFs/.docx), and which languages use signature-only extraction. Then `compile.py` walks the tree, hashes files, extracts skeletons, and queues enrichment jobs. **You are the LLM that synthesizes** — the script orchestrates and writes files but calls back to you for per-file `Purpose` notes and for concept synthesis. See `repokb/references/compilation.md`.

### `query` — the default operation

For any question about the indexed project:

1. Read `.repokb/MANIFEST.json` (always — it's tiny)
2. From `concepts[]`, pick 1–3 whose `topics` or `touches_sources` best match
3. Read only those concept files
4. If the user asks for verbatim code, resolve `<<source: path:start-end>>` directives by loading **only** those line ranges (file-read with `offset`+`limit`) — never the whole file

Do not list all concepts, do not preview them, do not "just to be safe" read more. If the right concept doesn't exist, run `update` — don't fall back to reading sources.

### `update` — incremental refresh

When the user says "refresh the KB" / "update after code changes":

```bash
python repokb/scripts/compile.py update --root .
```

The script diffs sha256 hashes against MANIFEST, re-extracts signatures, and marks affected concepts stale. **Body-only edits to code (no API change) cost zero tokens** — that's the central efficiency win. See `repokb/references/incremental.md`.

### `lint` — health checks

```bash
python repokb/scripts/compile.py lint --root .
```

Surfaces stale concepts, orphan summaries, broken wikilinks, over-budget concepts, adapter drift, and malformed `<<source:>>` directives. See `repokb/references/lint_rules.md`.

### `emit-adapters` — per-tool export

```bash
python repokb/scripts/compile.py emit-adapters --tools claude,codex,copilot,cursor
```

Generates `AGENTS.md`, `.github/copilot-instructions.md`, `.cursor/rules/repokb.mdc`, etc. from the canonical SKILL. Prints planned writes first; `--dry-run` to skip writing, `--diff-only` for CI. See `repokb/references/adapters.md`.

## MANIFEST contract

The only artifact loaded on every query. Full schema in `repokb/references/manifest_schema.md`. Essential fields:

```json
{
  "version": 2,
  "root": "/abs/path/to/repo",
  "updated_at": "2026-05-16T14:00:00Z",
  "stats": {"sources": 142, "summaries": 142, "concepts": 18},
  "concepts": [
    {
      "id": "auth-flow",
      "file": "concepts/auth-flow.md",
      "topics": ["JWT validation", "OAuth callback", "session expiry"],
      "touches_sources": ["src/auth/login.py", "src/auth/oauth.py"],
      "tokens_est": 1180,
      "stale": false
    }
  ]
}
```

`concepts[].topics` is what you read to route a query — keep it **specific** ("JWT validation in middleware"), not generic ("auth"). `touches_sources` powers incremental invalidation.

## Source directives

Concept pages embed inline pointers so verbatim retrieval is one targeted read away:

- `<<source: src/auth/jwt.py:42-67>>` — line range (preferred)
- `<<source: src/auth/jwt.py:42>>` — single line
- `<<source: src/auth/jwt.py>>` — whole file (discouraged; lint warns)

**Default: ignore them** — the synthesized concept already explains the topic. Only resolve when the user asks for verbatim code, exact line numbers, or wants to copy/modify the cited source, and then read **only the cited range**. Full grammar in `repokb/references/source_directives.md`.

## Concept page format

Markdown + YAML frontmatter in `.repokb/concepts/`, Obsidian-compatible. Each page:

- Self-contained for its scope — reader should not need to open sources
- Under ~1500 tokens (split if larger)
- Cites sources via `<<source:>>` directives
- Cross-links via `[[concept-id]]`
- Flags gaps with `<!-- gap: description -->`
- **Prefers prose-with-citation over pasted code blocks**

Template in `repokb/templates/concept_template.md`.

## Reading order

Load these only when the corresponding subtask is active:

| User intent | Read |
| --- | --- |
| Routine question about indexed project | Nothing more — MANIFEST + 1-3 concepts |
| First-time setup | `repokb/references/compilation.md` + `signatures.md` |
| "Refresh / update the KB" | `repokb/references/incremental.md` |
| Writing a `summarize_signature` enrichment | `repokb/references/signatures.md` |
| Lint findings need explanation | `repokb/references/lint_rules.md` |
| Emitting per-tool instruction files | `repokb/references/adapters.md` |
| Resolving a `<<source:>>` directive | `repokb/references/source_directives.md` |

Do **not** read every reference upfront — that defeats the skill's purpose.

## Token budgets

- MANIFEST.json: **<3000 tokens** (hard cap)
- Each concept page: **<1500 tokens** (split if larger)
- Each summary: **<400 tokens**
- Typical query: MANIFEST + 2 concepts ≈ **5000 tokens**

If you load more than 3 concepts for one question, either the question is too broad or the concept boundaries are wrong — flag it for re-synthesis.

## Non-goals

- **Not a code executor** — for "does this test pass?" you still need to run the test
- **Not a vector DB** — routing is by topic match against a tiny manifest
- **Not multi-user state** — commit `.repokb/` to share; merge conflicts are usually resolved by re-running `update`
- **Caps at ~80 concepts** — beyond that, switch to nested topic indexing (see `repokb/references/scaling.md`)
