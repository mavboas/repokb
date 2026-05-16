---
name: repokb
description: Compile and query a persistent, token-efficient knowledge base for a code repository or technical project. Use this skill whenever the user asks Claude to "understand", "remember", "index", "summarize", or "build a knowledge base of" a repo, codebase, docs folder, ADRs, RFCs, or any technical project — especially when the same project will be revisited across many conversations. Also use whenever the user mentions "OpenKB", "compiled wiki", "concept pages", "cross-document synthesis", or asks Claude to avoid re-reading the same files every session. This skill maintains a `.repokb/` directory with a MANIFEST, summaries, and synthesized concept pages so future queries load only a tiny index instead of raw source files, dramatically reducing token usage.
---

# RepoKB — Token-Efficient Knowledge Base for Code Projects

RepoKB is a Claude-native re-implementation of the OpenKB / Karpathy "compiled wiki" pattern, designed specifically for **technical project knowledge** (code, docs, ADRs, RFCs, runbooks) and optimized for **minimal token consumption** in Claude Code sessions.

The core insight: **traditional RAG and naive "read the repo" approaches rediscover knowledge on every query**. RepoKB compiles knowledge once into a persistent, layered wiki on disk, then keeps it current via content-hashed incremental updates. Future queries load a small index + 1-3 synthesized concept pages instead of raw source files.

## When to use this skill

Activate this skill when the user:

- Asks Claude to "learn", "index", "compile", "ingest", or "build a knowledge base" for a project, repo, or docs folder
- Wants Claude to answer questions about a codebase without re-uploading or re-reading files each session
- Mentions OpenKB, PageIndex, "compiled wiki", "concept pages", or Karpathy's LLM-KB workflow
- Complains about token usage, context bloat, or repetition when working on the same project across multiple conversations
- Asks to "update" or "refresh" an existing knowledge base after code changes
- Asks Claude to find contradictions, gaps, or stale information across project docs

Do NOT use this skill for one-off questions about files already in context, or for general web research.

## Mental model: three-layer progressive loading

```
.repokb/
├── MANIFEST.json          Layer 1 — always loaded (~1-3K tokens)
├── concepts/              Layer 2 — loaded on demand (1-3 files per query)
│   ├── auth-flow.md
│   ├── data-pipeline.md
│   └── error-handling.md
├── summaries/             Layer 3a — rarely loaded (only if concepts insufficient)
│   ├── src__auth__login.py.md
│   └── docs__architecture.md.md
├── sources/               Layer 3b — almost never loaded (only for verbatim citation)
│   └── (mirror of source paths, plus raw conversions for binary formats)
├── log.md                 Append-only operations history (for debugging)
└── config.yaml            Skill configuration
```

**The token math that makes this worth it:**

| Approach | Tokens per query (typical repo) |
| --- | --- |
| Naive "read the repo" | 50K – 500K |
| Traditional vector RAG | 5K – 20K (chunks, fragmented context) |
| **RepoKB** | **1.5K – 8K** (MANIFEST + 1-3 concepts) |

The dramatic savings come from three compounding wins:
1. **Index-only routing** — MANIFEST tells Claude which concepts exist before reading any
2. **Pre-computed synthesis** — concepts already merge insights from multiple sources
3. **Content-hashed incrementality** — only changed files trigger re-compilation

## Core workflow

The skill exposes five operations. **Always check `.repokb/MANIFEST.json` first** to determine which apply.

### 1. `init` — bootstrap a new knowledge base

When the user says "compile a KB for this repo" or "index this project", and no `.repokb/` exists yet:

```bash
python scripts/compile.py init --root . --config-from-interview
```

This creates `.repokb/`, writes a default `config.yaml`, and runs the initial ingestion. **Before running**, ask the user briefly:
- Which paths to include (default: everything tracked by git, minus common ignores)
- Which paths to exclude beyond `.gitignore` (e.g., generated code, vendored deps)
- Whether to ingest binary docs (PDFs, .docx in `docs/`) — defaults to yes

Then `scripts/compile.py` walks the tree, hashes each file, generates summaries, and synthesizes the initial concept pages. **You (Claude) are the LLM that does the synthesis** — the script orchestrates and writes files, but calls back to you for the actual summarization and concept generation. See `references/compilation.md` for the exact protocol.

### 2. `query` — answer a question with minimal tokens

This is the default operation for any question about the indexed project. **Read `MANIFEST.json` first** (it's tiny and always current), then:

1. From the MANIFEST's `concepts` list, pick 1-3 concept files whose `topics` or `touches_sources` best match the question
2. Read only those concept files
3. Answer

Only escalate to reading summaries or sources if the concept pages explicitly mark a gap (`<!-- gap: ... -->`) or the user asks for verbatim code/citation.

**Do not list all concepts, do not preview them, do not "just to be safe" read more than needed.** Trust the MANIFEST — that is what it is for. If the right concept does not exist, that is a signal to run `update`, not to fall back to reading sources.

### 3. `update` — incremental re-compilation

When the user has changed code and says "refresh the KB" or "update the index":

```bash
python scripts/compile.py update --root .
```

The script:
1. Re-walks the tree, recomputes sha256 of each file
2. Compares against `MANIFEST.json` hashes → produces a delta set (added, modified, removed, unchanged)
3. For each changed file, regenerates its summary
4. For each concept that `touches_sources` ∋ any changed file, marks it stale
5. Asks **you** (Claude) to re-synthesize only the stale concepts using the updated summaries

Unchanged files cost zero tokens. This is the central efficiency win for ongoing projects. See `references/incremental.md` for the diff protocol.

### 4. `lint` — health checks

```bash
python scripts/compile.py lint --root .
```

Surfaces: stale concepts (sources changed but concept not regenerated), orphans (summaries no concept references), contradictions flagged in concept frontmatter, broken wikilinks, and concepts that exceed a token budget (default 1500 tokens — they should be split).

### 5. `inspect` — debugging visibility

Quick read of `MANIFEST.json` + `log.md` tail. Useful when something seems off. Never reads concept bodies — keep it cheap.

## The MANIFEST.json contract

This file is the single source of truth and the only artifact loaded on every query. Keep it lean. Schema in `references/manifest_schema.md`, but the essence:

```json
{
  "version": 1,
  "root": "/abs/path/to/repo",
  "updated_at": "2026-05-16T14:00:00Z",
  "model_used": "claude-opus-4-7",
  "stats": {"sources": 142, "summaries": 142, "concepts": 18},
  "sources": [
    {
      "path": "src/auth/login.py",
      "sha256": "a3f...",
      "bytes": 4821,
      "summary": "summaries/src__auth__login.py.md",
      "tags": ["auth", "session"]
    }
  ],
  "concepts": [
    {
      "id": "auth-flow",
      "file": "concepts/auth-flow.md",
      "topics": ["authentication", "session management", "OAuth callback"],
      "touches_sources": ["src/auth/login.py", "src/auth/oauth.py", "docs/auth.md"],
      "tokens_est": 1180,
      "stale": false,
      "last_synthesized": "2026-05-16T14:00:00Z"
    }
  ]
}
```

The `concepts[].topics` field is **what Claude reads to route a query**. Keep it specific (not "general code", but "JWT validation in middleware"). The `touches_sources` field powers incremental invalidation.

## Concept page format

Concept pages live in `.repokb/concepts/` as plain Markdown with YAML frontmatter and `[[wikilinks]]` (Obsidian-compatible, so the user can browse the KB in Obsidian if they want).

Each concept page must:
- Be **self-contained** for its scope — a reader should not need to open sources to understand the concept at a high level
- Stay **under ~1500 tokens** — if it grows beyond that, split it
- Cite source files by **path + line range** so verbatim retrieval is one read away
- Cross-link related concepts via `[[concept-id]]`
- Flag gaps with `<!-- gap: description of what's missing -->` so future updates know what to fill

Template and example in `templates/concept_template.md`. Do not improvise the structure — consistency makes routing reliable.

## Reading order for this skill

When this skill activates, decide which of these to read based on the user's intent:

| User intent | Read |
| --- | --- |
| First-time setup ("compile this repo") | `references/compilation.md` |
| Routine question about indexed project | Nothing more — just `MANIFEST.json` + 1-3 concepts |
| "Refresh / update the KB" | `references/incremental.md` |
| Customizing concept structure | `references/manifest_schema.md` + `templates/concept_template.md` |
| Lint findings need explanation | `references/lint_rules.md` |

**Avoid reading every reference upfront.** That defeats the purpose of the skill. The reference files exist so they can be loaded **on demand** for the matching subtask, mirroring the same progressive-disclosure principle the skill itself applies to project knowledge.

## Non-goals and explicit limits

- **Not a replacement for code execution.** RepoKB summarizes; for "does this test pass?" you still need to run the test.
- **Not a vector DB.** No embeddings, no ANN. Routing is by topic match against a tiny manifest. This works because concepts are coarse-grained (10-50 per repo, not thousands).
- **Not multi-user.** The KB lives in the repo. If you need shared state across people, commit `.repokb/` (concepts, MANIFEST, summaries) and treat it like any other artifact — but be aware that summaries can be regenerated by anyone, so merge conflicts are usually resolvable by re-running `update`.
- **Cap on concepts.** If a repo would produce more than ~80 concepts, switch to nested topic indexing (see `references/scaling.md`). Below that, the flat list in MANIFEST is fine.

## Quick reference: token budget targets

- MANIFEST.json: **<3000 tokens** (hard cap; if exceeded, the source list is too verbose — trim tags, paths can stay)
- Each concept page: **<1500 tokens** (split if exceeded)
- Each summary: **<400 tokens** (one paragraph of purpose + key symbols/sections)
- Typical query context: **MANIFEST + 2 concepts ≈ 5000 tokens**

If you find yourself loading more than 3 concepts for a single question, either (a) the question is too broad — ask the user to narrow it, or (b) the concept structure is wrong — flag for the user that a re-synthesis with different topic boundaries might help.

## Failure modes to watch for

1. **Drift between sources and concepts.** Always run `update` before a query if the repo has been modified since `MANIFEST.updated_at`. The skill should check the mtime of the repo root against MANIFEST and warn if stale.
2. **Concepts that are just summaries in disguise.** A concept that references only one source is not pulling its weight — either merge it into a broader concept or demote it to a summary.
3. **MANIFEST bloat.** Per-source `tags` and `topics` are free-form; if Claude generates 20 tags per file, the manifest blows past its budget. The `compile.py` script enforces a max of 5 tags per source.
4. **Hash collisions on rename.** Renaming a file looks like delete + add. The script tries to detect renames via content hash; if it can't, the user may see a concept go briefly stale and then refresh.
