---
name: repokb
description: Compile and query a persistent, token-efficient knowledge base for a code repository or technical project. Use this skill whenever the user asks to "understand", "remember", "index", "summarize", or "build a knowledge base of" a repo, codebase, docs folder, ADRs, RFCs, or any technical project — especially when the same project will be revisited across many conversations. Also use whenever the user mentions "OpenKB", "compiled wiki", "concept pages", "cross-document synthesis", or asks to avoid re-reading the same files every session. This skill maintains a `.repokb/` directory with a MANIFEST, summaries, and synthesized concept pages so future queries load only a tiny index instead of raw source files, dramatically reducing token usage.
---

# RepoKB — Token-Efficient Knowledge Base for Code Projects

RepoKB is a multi-tool re-implementation of the OpenKB / Karpathy "compiled wiki" pattern, designed specifically for **technical project knowledge** (code, docs, ADRs, RFCs, runbooks) and optimized for **minimal token consumption** in LLM sessions.

The core insight: **traditional RAG and naive "read the repo" approaches rediscover knowledge on every query**. RepoKB compiles knowledge once into a persistent, layered wiki on disk, then keeps it current via content-hashed incremental updates. Future queries load a small index + 1-3 synthesized concept pages instead of raw source files.

## When to use this skill

Activate this skill when the user:

- Asks to "learn", "index", "compile", "ingest", or "build a knowledge base" for a project, repo, or docs folder
- Wants to answer questions about a codebase without re-uploading or re-reading files each session
- Mentions OpenKB, PageIndex, "compiled wiki", "concept pages", or Karpathy's LLM-KB workflow
- Complains about token usage, context bloat, or repetition when working on the same project across multiple conversations
- Asks to "update" or "refresh" an existing knowledge base after code changes
- Asks to find contradictions, gaps, or stale information across project docs

Do NOT use this skill for one-off questions about files already in context, or for general web research.

## Mental model: three-layer progressive loading

```
.repokb/
├── MANIFEST.json          Layer 1 — always loaded (~1-3K tokens)
├── concepts/              Layer 2 — loaded on demand (1-3 files per query)
│   ├── auth-flow.md
│   ├── data-pipeline.md
│   └── error-handling.md
├── signatures/            AST/regex skeletons for code files
│   └── src__auth__login.py.md
├── summaries/             Layer 3a — rarely loaded
│   ├── src__auth__login.py.md
│   └── docs__architecture.md.md
├── sources/               Layer 3b — almost never loaded
│   └── (mirror of source paths)
├── log.md                 Append-only operations history
└── config.yaml            Skill configuration
```

**The token math that makes this worth it:**

| Approach | Tokens per query |
| --- | --- |
| Naive "read the repo" | 50K – 500K |
| Traditional vector RAG | 5K – 20K |
| **RepoKB** | **1.5K – 8K** |

The dramatic savings come from:
1. **Index-only routing** — MANIFEST tells the LLM which concepts exist before reading any
2. **Pre-computed synthesis** — concepts already merge insights from multiple sources
3. **Content-hashed incrementality** — only changed files trigger re-compilation
4. **Signature skeletons + lazy source directives** — code-level inspection is targeted, not greedy

## Core workflow

### 1. `init` — bootstrap a new knowledge base

When the user says "compile a KB for this repo" or "index this project":

```bash
python repokb/scripts/compile.py init --root . --config-from-interview
```

This creates `.repokb/`, writes a default `config.yaml`, and runs initial ingestion. The script:
- Walks the tree and extracts AST/regex signatures for code files
- Generates per-file summaries (purpose + key symbols/sections)
- Synthesizes cross-document concepts
- Emits MANIFEST.json with routing metadata

### 2. `update` — keep the KB current

When the user says "update the KB" or "refresh after code changes":

```bash
python repokb/scripts/compile.py update --root .
```

Only changed files trigger re-compilation. Body-only edits to code (implementation changes without API changes) cost zero tokens.

### 3. `query` — ask questions that span the KB

After KB is initialized, for any question about the codebase:

1. Load `.repokb/MANIFEST.json` (always — it's tiny)
2. Identify which concepts (Layer 2) match the question's topics
3. Load 1-3 concept pages
4. If user asks for verbatim code, use `<<source: path:start-end>>` directives to load only cited line ranges

### 4. `lint` — health checks

```bash
python repokb/scripts/compile.py lint --root .
```

Validates: stale concepts, orphaned summaries, broken wikilinks, token budgets exceeded, adapter drift, and malformed directives.

### 5. `emit-adapters` — multi-tool export

```bash
python repokb/scripts/compile.py emit-adapters --tools claude,codex,copilot,cursor
```

Generates per-tool instruction files from the canonical SKILL.md (Claude `.md`, Copilot `.github/copilot-instructions.md`, etc.).

## Performance

RepoKB typically reduces token consumption by **90%+** compared to naive "read the whole repo" approaches:

- **MANIFEST only**: ~1-3K tokens (routing)
- **+ 1-3 concept pages**: ~4-8K tokens (typical query)
- **Full source fallback**: >50K tokens (rarely needed)

See [README.md](./README.md) for evaluation results against test repositories.

## The MANIFEST.json contract

This file is the single source of truth and only artifact loaded on every query. Schema in `repokb/references/manifest_schema.md`, but key fields:

```json
{
  "version": 2,
  "root": "/abs/path/to/repo",
  "host_tool": "copilot",
  "updated_at": "2026-05-16T14:00:00Z",
  "stats": {"sources": 142, "summaries": 142, "concepts": 18},
  "concepts": [
    {
      "id": "auth-flow",
      "file": "concepts/auth-flow.md",
      "topics": ["authentication", "session management", "OAuth"],
      "touches_sources": ["src/auth/login.py", "src/auth/oauth.py"],
      "tokens_est": 1180,
      "stale": false
    }
  ]
}
```

The `concepts[].topics` field enables precise routing. Keep it specific, not generic.

## Source directive protocol

Concept pages embed inline directives to enable targeted code retrieval:

```
The validate_jwt function at <<source: src/auth/jwt.py:42-67>> rejects expired tokens.
```

When the user asks for verbatim code or exact references, resolve directives by loading **only** those line ranges (never whole files). This keeps queries small even when concepts cite many sources.

See `repokb/references/source_directives.md` for full details.

## Concept page format

Concept pages live in `.repokb/concepts/` as Markdown with YAML frontmatter:

- Self-contained for their scope — reader should grasp the concept without opening sources
- Under ~1500 tokens (split if larger)
- Cite sources via `<<source:>>` directives
- Cross-link related concepts via `[[concept-id]]`
- Flag gaps with `<!-- gap: description -->` for future updates
- Prefer prose-with-citation over pasted code blocks

See `repokb/templates/concept_template.md` for structure.

## Setup and installation

1. **Install via npm:**
   ```bash
   npx skills add https://github.com/mavboas/repokb
   ```

2. **Initialize a KB for your repo:**
   ```bash
   python repokb/scripts/compile.py init --root /path/to/your/repo
   ```

3. **Query the KB in your LLM sessions:**
   - Ask questions; the KB loads automatically
   - Run `update` after code changes
   - Check `.repokb/MANIFEST.json` to see compiled concepts

## Multi-tool export

Export the skill for different LLM platforms:

```bash
# Claude
python repokb/scripts/compile.py emit-adapters --tools claude

# GitHub Copilot
python repokb/scripts/compile.py emit-adapters --tools copilot

# Cursor
python repokb/scripts/compile.py emit-adapters --tools cursor

# All at once
python repokb/scripts/compile.py emit-adapters --tools claude,codex,copilot,cursor
```

## Documentation

- [Manifest Schema](./repokb/references/manifest_schema.md) — MANIFEST.json structure
- [Compilation Process](./repokb/references/compilation.md) — How `init` and `update` work
- [Signatures](./repokb/references/signatures.md) — AST and regex extraction
- [Incremental Updates](./repokb/references/incremental.md) — Diff protocol for `update`
- [Lint Rules](./repokb/references/lint_rules.md) — Validation rules
- [Source Directives](./repokb/references/source_directives.md) — `<<source:>>` grammar
- [Adapters](./repokb/references/adapters.md) — Multi-tool export

## Quick reference: token budget targets

- **MANIFEST.json**: <3000 tokens
- **Each concept page**: <1500 tokens (split if larger)
- **Each summary**: <400 tokens
- **Each signature**: <500 tokens
- **Typical query**: MANIFEST + 2 concepts ≈ 5000 tokens

## License

See [LICENSE](./LICENSE).
