<!-- TOOL:only name="claude" -->
---
name: repokb
description: Compile and query a persistent, token-efficient knowledge base for a code repository or technical project. Use this skill whenever the user asks {{TOOL_DISPLAY}} to "understand", "remember", "index", "summarize", or "build a knowledge base of" a repo, codebase, docs folder, ADRs, RFCs, or any technical project — especially when the same project will be revisited across many conversations. Also use whenever the user mentions "OpenKB", "compiled wiki", "concept pages", "cross-document synthesis", or asks {{TOOL_DISPLAY}} to avoid re-reading the same files every session. This skill maintains a `.repokb/` directory with a MANIFEST, summaries, and synthesized concept pages so future queries load only a tiny index instead of raw source files, dramatically reducing token usage.
---
<!-- TOOL:end -->

<!-- TOOL:except name="claude" -->
**CRITICAL: Do NOT load full source files when a concept contains `<<source:>>` directives. Use your file-read tool with offset+limit to load only the cited line ranges.**

<!-- TOOL:end -->

# RepoKB — Token-Efficient Knowledge Base for Code Projects

RepoKB is a multi-tool re-implementation of the OpenKB / Karpathy "compiled wiki" pattern, designed specifically for **technical project knowledge** (code, docs, ADRs, RFCs, runbooks) and optimized for **minimal token consumption** in {{TOOL_DISPLAY}} sessions.

The core insight: **traditional RAG and naive "read the repo" approaches rediscover knowledge on every query**. RepoKB compiles knowledge once into a persistent, layered wiki on disk, then keeps it current via content-hashed incremental updates. Future queries load a small index + 1-3 synthesized concept pages instead of raw source files.

<!-- TOOL:only name="claude" -->
## When to use this skill

Activate this skill when the user:

- Asks {{TOOL_DISPLAY}} to "learn", "index", "compile", "ingest", or "build a knowledge base" for a project, repo, or docs folder
- Wants {{TOOL_DISPLAY}} to answer questions about a codebase without re-uploading or re-reading files each session
- Mentions OpenKB, PageIndex, "compiled wiki", "concept pages", or Karpathy's LLM-KB workflow
- Complains about token usage, context bloat, or repetition when working on the same project across multiple conversations
- Asks to "update" or "refresh" an existing knowledge base after code changes
- Asks {{TOOL_DISPLAY}} to find contradictions, gaps, or stale information across project docs

Do NOT use this skill for one-off questions about files already in context, or for general web research.
<!-- TOOL:end -->

<!-- TOOL:except name="claude" -->
## When this protocol applies

{{INVOCATION_HINT}}

Use it whenever the user:

- Asks you to learn, index, compile, or build a knowledge base for the repo
- Asks questions about the codebase that could be answered from a prior compilation
- Mentions OpenKB, compiled wiki, concept pages, RepoKB, or the `.repokb/` directory
- Asks to update or refresh the knowledge base after code changes

Do NOT engage this protocol for one-off questions about files already in your context, or for tasks unrelated to the indexed project.
<!-- TOOL:end -->

## Mental model: three-layer progressive loading

```
.repokb/
├── MANIFEST.json          Layer 1 — always loaded (~1-3K tokens)
├── concepts/              Layer 2 — loaded on demand (1-3 files per query)
│   ├── auth-flow.md
│   ├── data-pipeline.md
│   └── error-handling.md
├── signatures/            AST/regex skeletons for code files (cheap to (re)build)
│   └── src__auth__login.py.md
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

The dramatic savings come from four compounding wins:
1. **Index-only routing** — MANIFEST tells {{TOOL_DISPLAY}} which concepts exist before reading any
2. **Pre-computed synthesis** — concepts already merge insights from multiple sources
3. **Content-hashed incrementality** — only changed files trigger re-compilation
4. **Signature-only skeletons + lazy `<<source:>>` directives** — even code-level inspection is targeted, not greedy

## Core workflow

The skill exposes the operations below. **Always check `.repokb/MANIFEST.json` first** to determine which apply.

### 1. `init` — bootstrap a new knowledge base

When the user says "compile a KB for this repo" or "index this project", and no `.repokb/` exists yet:

```bash
python scripts/compile.py init --root . --config-from-interview
```

This creates `.repokb/`, writes a default `config.yaml`, and runs the initial ingestion. **Before running**, ask the user briefly:
- Which paths to include (default: everything tracked by git, minus common ignores)
- Which paths to exclude beyond `.gitignore` (e.g., generated code, vendored deps)
- Whether to ingest binary docs (PDFs, .docx in `docs/`) — defaults to yes
- Which languages should use signature-only extraction (default: Python via AST, JS/TS/Go/Rust via regex)

Then `scripts/compile.py` walks the tree, hashes each file, extracts AST/regex skeletons for code files, and emits a work queue. **You ({{TOOL_DISPLAY}}) are the LLM that does the enrichment and synthesis** — the script orchestrates and writes files, but calls back to you for `Purpose` + `Notable decisions` on each file and for concept synthesis. See `references/compilation.md` and `references/signatures.md` for the exact protocol.

### 2. `query` — answer a question with minimal tokens

This is the default operation for any question about the indexed project. **Read `MANIFEST.json` first** (it's tiny and always current), then:

1. From the MANIFEST's `concepts` list, pick 1-3 concept files whose `topics` or `touches_sources` best match the question
2. Read only those concept files
3. If the concept page contains `<<source: path:start-end>>` directives and the user asks for verbatim code or exact references, resolve those directives by loading **only** the cited line ranges (your file-read tool with offset+limit) — never the whole file
4. Answer

Only escalate to reading summaries or sources if the concept pages explicitly mark a gap (`<!-- gap: ... -->`) or the user asks for verbatim code outside the directive ranges.

**Do not list all concepts, do not preview them, do not "just to be safe" read more than needed.** Trust the MANIFEST — that is what it is for. If the right concept does not exist, that is a signal to run `update`, not to fall back to reading sources.

### 3. `update` — incremental re-compilation

When the user has changed code and says "refresh the KB" or "update the index":

```bash
python scripts/compile.py update --root .
```

The script:
1. Re-walks the tree, recomputes sha256 of each file
2. Compares against `MANIFEST.json` hashes → produces a delta set (added, modified, removed, unchanged)
3. For each changed code file, re-runs signature extraction. If the signature is unchanged (body-only edit), skips the LLM job entirely.
4. For each changed file whose signature did change, queues a `summarize_signature` (code) or `summarize` (prose) job.
5. For each concept that `touches_sources` ∋ any changed file, marks it stale
6. Asks **you** ({{TOOL_DISPLAY}}) to re-synthesize only the stale concepts using the updated summaries, with directive-range updates pre-computed.

Unchanged files cost zero tokens. Body-only edits to code files also cost zero tokens. This is the central efficiency win for ongoing projects. See `references/incremental.md` for the diff protocol.

### 4. `lint` — health checks

```bash
python scripts/compile.py lint --root .
```

Surfaces: stale concepts (sources changed but concept not regenerated), orphans (summaries no concept references), contradictions flagged in concept frontmatter, broken wikilinks, concepts that exceed a token budget (default {{MAX_CONCEPT_TOKENS}} tokens — they should be split), adapter drift (emitted instruction files out of sync with the canonical SKILL.md), and orphan directives (`<<source:>>` pointers to paths not in `touches_sources`).

### 5. `inspect` — debugging visibility

Quick read of `MANIFEST.json` + `log.md` tail. Useful when something seems off. Never reads concept bodies — keep it cheap. Pass `--directive-stats` to summarize how often `<<source:>>` directives are being resolved as ranges vs whole-file loads.

### 6. `emit-adapters` — generate per-tool instruction files

```bash
python scripts/compile.py emit-adapters --tools claude,codex,copilot,cursor
```

Generates `AGENTS.md`, `.github/copilot-instructions.md`, `.cursor/rules/repokb.mdc`, etc. from the canonical SKILL.md. Always prints planned writes first; pass `--yes` to skip the prompt, `--dry-run` to skip writing, `--diff-only` for CI. See `references/adapters.md`.

## The MANIFEST.json contract

This file is the single source of truth and the only artifact loaded on every query. Keep it lean. Schema in `references/manifest_schema.md`, but the essence:

```json
{
  "version": 2,
  "root": "/abs/path/to/repo",
  "host_tool": "{{TOOL_NAME}}",
  "updated_at": "2026-05-16T14:00:00Z",
  "model_used": "{{TOOL_DISPLAY}}",
  "stats": {"sources": 142, "summaries": 142, "concepts": 18},
  "sources": [
    {
      "path": "src/auth/login.py",
      "sha256": "a3f...",
      "sig_sha256": "b9e...",
      "signature_source": "ast",
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
      "source_directives": [
        {"path": "src/auth/login.py", "start": 42, "end": 67},
        {"path": "src/auth/oauth.py", "start": 18, "end": 30}
      ],
      "tokens_est": 1180,
      "stale": false,
      "last_synthesized": "2026-05-16T14:00:00Z"
    }
  ]
}
```

The `concepts[].topics` field is **what you read to route a query**. Keep it specific (not "general code", but "JWT validation in middleware"). The `touches_sources` field powers incremental invalidation. The `source_directives` mirror lets `lint` validate directives without re-parsing concept Markdown.

## Source directive protocol

Concept pages embed inline directives like `<<source: path:start-end>>` so you can load exact line ranges only when needed.

**Forms:**
- `<<source: src/auth/jwt.py:42-67>>` — line range (preferred)
- `<<source: src/auth/jwt.py:42>>` — single line
- `<<source: src/auth/jwt.py>>` — whole file (discouraged; lint warns)

**What you do with them:**
1. Default: ignore them. The synthesized concept already explains the topic.
2. If the user asks for verbatim code, exact line numbers, or wants to copy/modify the cited source: find the matching directive and read ONLY that line range using your file-read tool with `offset=start, limit=(end-start+1)`. Never load the whole file.

This contract is what keeps queries small even when concepts cite many files. See `references/source_directives.md` for the full grammar, including refresh-time propagation and the optional audit log.

## Concept page format

Concept pages live in `.repokb/concepts/` as plain Markdown with YAML frontmatter and `[[wikilinks]]` (Obsidian-compatible, so the user can browse the KB in Obsidian if they want).

Each concept page must:
- Be **self-contained** for its scope — a reader should not need to open sources to understand the concept at a high level
- Stay **under ~{{MAX_CONCEPT_TOKENS}} tokens** — if it grows beyond that, split it
- Cite source files via `<<source:>>` directives so verbatim retrieval is one targeted read away
- Cross-link related concepts via `[[concept-id]]`
- Flag gaps with `<!-- gap: description of what's missing -->` so future updates know what to fill
- **Prefer prose-with-citation over fenced code blocks.** "The `validate_jwt` function at `<<source: src/auth/jwt.py:42-67>>` rejects expired tokens" earns its tokens; pasting the function body does not.

Template and example in `templates/concept_template.md`. Do not improvise the structure — consistency makes routing reliable.

## Reading order for this skill

When this skill activates, decide which of these to read based on the user's intent:

| User intent | Read |
| --- | --- |
| First-time setup ("compile this repo") | `references/compilation.md` + `references/signatures.md` |
| Routine question about indexed project | Nothing more — just `MANIFEST.json` + 1-3 concepts |
| "Refresh / update the KB" | `references/incremental.md` |
| Customizing concept structure | `references/manifest_schema.md` + `templates/concept_template.md` |
| Writing a `summarize_signature` enrichment | `references/signatures.md` + `templates/signature_summary_template.md` |
| Lint findings need explanation | `references/lint_rules.md` |
| Emitting per-tool instruction files | `references/adapters.md` |
| Resolving a `<<source:>>` directive | `references/source_directives.md` |

**Avoid reading every reference upfront.** That defeats the purpose of the skill. The reference files exist so they can be loaded **on demand** for the matching subtask, mirroring the same progressive-disclosure principle the skill itself applies to project knowledge.

## Non-goals and explicit limits

- **Not a replacement for code execution.** RepoKB summarizes; for "does this test pass?" you still need to run the test.
- **Not a vector DB.** No embeddings, no ANN. Routing is by topic match against a tiny manifest. This works because concepts are coarse-grained (10-50 per repo, not thousands).
- **Not multi-user.** The KB lives in the repo. If you need shared state across people, commit `.repokb/` (concepts, MANIFEST, summaries, signatures) and treat it like any other artifact — but be aware that summaries can be regenerated by anyone, so merge conflicts are usually resolvable by re-running `update`.
- **Cap on concepts.** If a repo would produce more than ~80 concepts, switch to nested topic indexing (see `references/scaling.md`). Below that, the flat list in MANIFEST is fine.

## Quick reference: token budget targets

- MANIFEST.json: **<{{MANIFEST_TOKEN_CAP}} tokens** (hard cap; if exceeded, the source list is too verbose — trim tags, paths can stay)
- Each concept page: **<{{MAX_CONCEPT_TOKENS}} tokens** (split if exceeded)
- Each summary: **<400 tokens** (one paragraph of purpose + key symbols/sections)
- Each signature skeleton: **<500 tokens for most files** (read directly when working a `summarize_signature` job)
- Typical query context: **MANIFEST + 2 concepts ≈ 5000 tokens**

If you find yourself loading more than 3 concepts for a single question, either (a) the question is too broad — ask the user to narrow it, or (b) the concept structure is wrong — flag for the user that a re-synthesis with different topic boundaries might help.

## Failure modes to watch for

1. **Drift between sources and concepts.** Always run `update` before a query if the repo has been modified since `MANIFEST.updated_at`. The skill should check the mtime of the repo root against MANIFEST and warn if stale.
2. **Concepts that are just summaries in disguise.** A concept that references only one source is not pulling its weight — either merge it into a broader concept or demote it to a summary.
3. **MANIFEST bloat.** Per-source `tags` and `topics` are free-form; if you generate 20 tags per file, the manifest blows past its budget. The `compile.py` script enforces a max of 5 tags per source.
4. **Hash collisions on rename.** Renaming a file looks like delete + add. The script tries to detect renames via content hash; if it can't, the user may see a concept go briefly stale and then refresh.
5. **Loading whole files when directives exist.** This defeats the point of the directive protocol. If you find yourself doing it, re-read `references/source_directives.md` — almost always the cited range is enough.
6. **Adapter drift.** If a hand-edit happens to `AGENTS.md` or `.github/copilot-instructions.md` outside the sentinel block, `lint` STRUCT-07 will catch it. Re-run `emit-adapters --diff-only` to see the drift, then either accept by re-emitting or revert the edit.
