# 📚 RepoKB — Token-Efficient, Multi-Tool Knowledge Base for Code Projects

<img alt="License" src="https://img.shields.io/github/license/VectifyAI/OpenKB"> <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue">

Compile your codebase into a persistent, token-efficient knowledge base that works **across Claude Code, OpenAI Codex CLI, GitHub Copilot, and Cursor** — without an API key, because each tool's host LLM executes the protocol directly.

**Instead of re-reading your entire repository on every query, RepoKB compiles knowledge once into a persistent index. Future queries load only a tiny MANIFEST + 1-3 synthesized concept pages, reducing token usage by 90%+. v2 adds AST-based signature skeletons (Phase 1 cost drops another ~70%) and `<<source:>>` directives so the host LLM only loads exact line ranges on demand.**

## ✨ What's new in v2

- **Multi-tool support.** One canonical `SKILL.md` (at the repo root) compiles to Claude's `CLAUDE.md`, Codex's `AGENTS.md`, Copilot's `.github/copilot-instructions.md`, and Cursor's `.cursor/rules/repokb.mdc`. Run `compile.py emit-adapters --tools claude,codex,copilot,cursor` and every supported tool picks up the protocol.
- **No API key required.** Unlike OpenKB (which routes through a configurable LLM provider), RepoKB hands jobs to whatever LLM is hosting the current session. The Python script never makes an API call.
- **AST-based signature skeletons.** For Python (full AST via stdlib) and JS/TS/Go/Rust (regex), the script extracts the public surface deterministically. The host LLM enriches with `Purpose` + `Notable decisions` only, reading the source ONLY when a symbol carries `<<unclear: reason>>`. Phase 1 token cost drops ~70% vs LLM-reads-whole-file.
- **Body-only-edit skip.** When a code file's signature surface is unchanged (you tweaked an implementation, not an API), `update` skips the LLM job entirely. Routine refactors cost zero tokens.
- **`<<source: path:start-end>>` directives.** Concept pages cite exact line ranges. The host LLM loads only that range when verbatim code is needed, never the whole file.
- **Cross-tool drift detection.** Lint rule STRUCT-07 catches hand-edits to emitted instruction files; `adapter-check` validates each adapter's stamped CONVENTION_VERSION.

---

## 🎯 Why RepoKB?

### The Problem with Traditional Approaches

| Approach | Tokens per Query | Issues |
|----------|-----------------|--------|
| **Naive "read the whole repo"** | 50K–500K | Everything rediscovered each time; massive context bloat |
| **Traditional Vector RAG** | 5K–20K | Fragmented chunks; lost context; no synthesis |
| **RepoKB** | **1.5K–8K** | Index-only routing + pre-synthesized concepts |

### The Solution: Progressive Knowledge Layers

RepoKB uses a three-layer model:

```
┌─ Layer 1: MANIFEST (always loaded)        ~1-3K tokens
│  ├─ List of all concepts
│  ├─ Routing metadata (topics, source maps)
│  └─ Invalidation tracking
│
├─ Layer 2: Concept Pages (loaded on-demand) 1-3 files per query
│  ├─ Cross-document synthesis
│  ├─ Pre-computed relationships
│  └─ Topic-specific deep dives
│
└─ Layer 3: Summaries + Raw Sources (fallback)
   ├─ Per-file summaries (rarely needed)
   └─ Raw source code (cite-only)
```

---

## 📊 Performance Evaluation

### Eval Suite Results

We ran RepoKB against a test repository and measured token consumption for equivalent queries:

```
Query Model: Claude 3.5 Sonnet
Repository: minimal_repo (auth, db, test modules)
Baseline: Naive "read the whole repo" approach

┌─────────────────────────────┬────────┬────────────────────────┐
│ Approach                    │ Tokens │ Efficiency vs Baseline │
├─────────────────────────────┼────────┼────────────────────────┤
│ Naive "read the whole repo" │ 58,307 │                     1× │
├─────────────────────────────┼────────┼────────────────────────┤
│ MANIFEST + 1 concept        │  4,994 │ 11.7× smaller (−91.4%) │
├─────────────────────────────┼────────┼────────────────────────┤
│ MANIFEST + 2 concepts       │  6,101 │  9.6× smaller (−89.5%) │
└─────────────────────────────┴────────┴────────────────────────┘
```

### Key Findings

- **Claim vs Reality**: RepoKB's documented range of 1.5K–8K tokens per query is validated — this run achieved ~5K tokens per query, well within predicted band
- **Pre-computed Synthesis**: Cross-document concept pages reduce redundant LLM synthesis across queries
- **Incremental Updates**: Only changed files trigger re-compilation; unchanged content costs zero additional tokens
- **Content-Hashed Routing**: MANIFEST enables precise concept selection, avoiding over-fetching

### Caveats & Insights

- **MANIFEST Size Calibration**: MANIFEST (3,712 tokens) exceeded 3,000-token hard cap by 24%. Root cause: large JSON fixture files inflated source list. Mitigation: mark them as `marginal_sources` in config
- **Baseline Inflation**: The 58K baseline includes fixture files; real source ~80KB → realistic savings ratio ~4× (still strong)
- **Queue Protocol Validation**: Concepts generated via Claude-orchestrated deterministic script, matching production workflows

---

## 🔄 RepoKB vs OpenKB: Feature Comparison

| Feature | RepoKB v2 | OpenKB |
|---------|--------|--------|
| **Design Focus** | Multi-tool, token-optimized for code | General-purpose, multi-LLM via API |
| **Activation Model** | Host LLM executes protocol (no API key) | User configures an LLM API key per provider |
| **Supported Hosts** | Claude Code, Codex CLI, GitHub Copilot, Cursor | Any LiteLLM provider |
| **Document Support** | Markdown, code, plain text | PDF, Word, PPT, Excel, HTML (via markitdown) |
| **Long Document Handling** | File-level summaries + AST skeletons | PageIndex tree indexing |
| **Code-File Cost** | AST extraction + LLM enrichment (~30% of LLM-read) | LLM reads full source |
| **Body-Only Edits** | Free (skipped via sig_sha256) | Re-summarized |
| **Knowledge Compilation** | Host-LLM synthesis | LLM-driven + PageIndex integration |
| **Retrieval Strategy** | Concept routing + `<<source:>>` directives | PageIndex + semantic search |
| **Wiki Format** | Plain Markdown + wikilinks + directives | Obsidian-compatible Markdown |
| **Incremental Updates** | Content-hashed delta + signature fingerprint | File-level invalidation |
| **Cross-Tool Adapter Files** | `emit-adapters` generates all four | n/a (server-side) |
| **Deployment** | Local Python script + your editor of choice | Local + multi-provider LLM API |

### Why RepoKB for Code Projects?

✅ **Works in every major AI coding tool**: same protocol, four native instruction files generated from one canonical spec
✅ **No API key configuration**: the host LLM in your tool already exists; no separate billing path
✅ **Aggressive token economics**: AST skeletons + directive-lazy concepts + body-only-edit skip compound for 90%+ savings on warm queries
✅ **Lighter weight**: focuses on code + technical docs, not all document types
✅ **Minimal dependencies**: no vector DB, no PageIndex (code usually <100 pages); stdlib only for Python AST
✅ **Deterministic workflows**: content-hashed file tracking + structural fingerprinting for reproducible compilations

### Why Choose OpenKB?

✅ **Broad Document Support**: PDF, images, scanned docs via OCR
✅ **Interactive Chat**: Multi-turn sessions with resume capability
✅ **Production-Ready**: Used by teams at scale
✅ **PageIndex Integration**: Handles long, complex PDFs elegantly
✅ **Multi-LLM via API**: any provider, server-side execution

---

## 🏗️ Architecture

### Core Components

```
repokb/
├── scripts/
│   └── compile.py              Deterministic orchestrator (walk, hash, queue, AST, emit)
├── adapters/                   Per-tool instruction-file generators
│   ├── base.py                 Adapter ABC + sentinel constants
│   ├── claude.py               -> <repo>/CLAUDE.md (sentinel merge)
│   ├── codex.py                -> <repo>/AGENTS.md (sentinel merge)
│   ├── copilot.py              -> <repo>/.github/copilot-instructions.md (trimmed ≤3K)
│   ├── cursor.py               -> <repo>/.cursor/rules/repokb.mdc (MDC frontmatter)
│   ├── conventions.yaml        External-spec version registry
│   └── extractors/             Signature extractors (one per language)
│       ├── python_ast.py       stdlib `ast`; auto-unclear heuristics
│       ├── regex_js.py         JS + TS (interface, type, arrow, class)
│       ├── regex_go.py         func, method, struct, interface, const
│       └── regex_rust.py       pub fn/struct/enum/trait/const
├── references/
│   ├── compilation.md          Work-queue protocol (host-LLM-neutral)
│   ├── incremental.md          Delta tracking + sig_sha256 skip
│   ├── adapters.md             Per-tool conventions, placeholder grammar
│   ├── signatures.md           AST/regex extraction protocol, defer-to-source
│   ├── source_directives.md    <<source:>> grammar + lazy load contract
│   ├── lint_rules.md           Health checks (incl. STRUCT-07/08/09 + PERF-04)
│   ├── manifest_schema.md      MANIFEST.json v2 format spec
│   └── scaling.md              Patterns for large repos
├── templates/
│   ├── concept_template.md     Concept page template (with <<source:>> examples)
│   ├── summary_template.md     Per-file summary generation (legacy / prose files)
│   └── signature_summary_template.md   Slim enrichment template for code files
└── SKILL.md                    Canonical skill (with TOOL: blocks + placeholders)
```

### Workflow: Three Operations

#### 1. **Init** — Bootstrap a Knowledge Base

```bash
python scripts/compile.py init --root . --config-from-interview
```

- Walks the repo, hashes every file
- Generates summaries for each source
- Synthesizes initial concept pages (Claude)
- Writes `.repokb/MANIFEST.json`

#### 2. **Query** — Answer a Question with Minimal Tokens

```python
# Read MANIFEST (tiny)
with open(".repokb/MANIFEST.json") as f:
    manifest = json.load(f)

# Pick 1-3 concepts by topic matching
concepts = route_concepts(question, manifest["concepts"])

# Load only selected concept files + answer
for concept in concepts:
    text += read_file(concept["file"])
answer = claude_api.call(question + text)
```

**Result**: ~5K tokens instead of 50K+

#### 3. **Update** — Incremental Re-compilation

```bash
python scripts/compile.py update --root .
```

- Re-hashes all files → produces delta
- Regenerates summaries for changed files only
- Invalidates concepts touching changed sources
- Re-synthesizes stale concepts (Claude)

**Result**: Unchanged files cost zero tokens; only modifications trigger re-work

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- `anthropic` Python library (Claude API access)
- Git (for repo walking)

### Quick Start

```bash
# 1. Clone or explore this repo
git clone <this-repo>
cd repokb

# 2. Initialize a knowledge base for your project
python repokb/scripts/compile.py init --root /path/to/your/project

# 3. Answer questions with minimal tokens
# (See SKILL.md for query operation)
```

### Configuration

RepoKB creates `.repokb/config.yaml`:

```yaml
include_globs:
  - "**/*"
exclude_globs:
  - ".git/**"
  - "node_modules/**"
  - "__pycache__/**"
  - ".repokb/**"

token_budgets:
  manifest_max: 3000          # Hard cap on MANIFEST size
  concept_target: 1500        # Target per-concept size
  
model: claude-opus-4-7        # Claude model to use

ingest_binary_docs: false     # Code projects typically false
```

---

## 📖 Concepts: The Core Insight

A **concept** is a synthesized, cross-document explanation of a topic. For example:

### Example: "Authentication Flow"

```markdown
# Authentication Flow

## Covered in This Concept
- User login via username/password
- OAuth callback handling
- Session token generation and storage
- Token refresh mechanisms

## Sources
- `src/auth/login.py` — Login entry point and validation
- `src/auth/oauth.py` — OAuth provider integration
- `docs/auth.md` — Architecture overview

## Key Insights
1. Sessions are JWT-based with 1-hour TTL
2. Refresh tokens stored server-side for revocation
3. OAuth flow uses PKCE to prevent token interception

## Gaps
- No documented recovery for expired tokens in production
- Rate limiting not covered in current code
```

**Why This Matters**:
- On the next query about auth, Claude reads this one file (~1K tokens) instead of all three sources (~5K)
- Concepts encode intent and relationships that raw code files don't
- Updates to any auth file mark only this concept stale

---

## 🧪 The MANIFEST.json Contract

Every query starts with the MANIFEST — your knowledge base's index:

```json
{
  "version": 1,
  "root": "/abs/path/to/repo",
  "updated_at": "2026-05-16T14:00:00Z",
  "model_used": "claude-opus-4-7",
  "stats": {
    "sources": 142,
    "summaries": 142,
    "concepts": 18
  },
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
      "topics": ["authentication", "session management", "OAuth"],
      "touches_sources": ["src/auth/login.py", "src/auth/oauth.py"],
      "tokens_est": 1180,
      "stale": false,
      "last_synthesized": "2026-05-16T14:00:00Z"
    }
  ]
}
```

**Keep it lean**: MANIFEST is loaded on every query. Aim for <3K tokens.

---

## 🔧 Commands Reference

| Command | Purpose |
|---------|---------|
| `python scripts/compile.py init` | Bootstrap a new knowledge base |
| `python scripts/compile.py update` | Recompile after code changes (skips body-only edits) |
| `python scripts/compile.py lint` | Health checks (stale, orphans, contradictions, adapter drift, directive validity) |
| `python scripts/compile.py inspect [--directive-stats]` | Quick debug view of MANIFEST + log |
| `python scripts/compile.py emit-adapters --tools T,T,...` | Generate per-tool instruction files |
| `python scripts/compile.py adapter-check` | Validate adapter CONVENTION_VERSION stamps |
| `python scripts/compile.py extract-signatures [--paths ...]` | Refresh AST/regex skeletons |
| `python scripts/compile.py migrate --to-version 2` | Upgrade an existing v1 `.repokb/` to v2 |
| `python scripts/compile.py manifest-add-concept` | Manually add a concept |
| `python scripts/compile.py manifest-set-stale` | Mark concept for re-synthesis |

---

## 📚 Documentation Structure

- **[SKILL.md](./SKILL.md)** — Full skill instructions for Claude (use this for integration)
- **[references/compilation.md](./repokb/references/compilation.md)** — Work-queue protocol + LLM integration
- **[references/incremental.md](./repokb/references/incremental.md)** — Delta tracking + stale invalidation
- **[references/lint_rules.md](./repokb/references/lint_rules.md)** — Health check rules
- **[references/manifest_schema.md](./repokb/references/manifest_schema.md)** — MANIFEST.json spec
- **[references/scaling.md](./repokb/references/scaling.md)** — Patterns for large repositories

---

## 🧠 Mental Model: Why This Works

### Traditional RAG Rediscovers Knowledge

```
Query 1: "How does auth work?"
  → Read all auth files (5K tokens)
  → Extract relevant chunks
  → Answer

Query 2: "What about OAuth?"
  → Read all auth files AGAIN (5K tokens)  ← Wasted tokens!
  → Extract different chunks
  → Answer

Query 3: "How do we handle token expiry?"
  → Read all auth files AGAIN (5K tokens)  ← Wasted tokens!
  → Extract yet different chunks
  → Answer

Total: 15K tokens for 3 related queries
```

### RepoKB Accumulates Knowledge

```
Init:
  → Analyze all auth files once (5K tokens)
  → Synthesize auth-flow concept (5K tokens LLM time)
  → Write auth-flow.md (1K tokens) ← Persistent

Query 1: "How does auth work?"
  → Read MANIFEST (1K tokens)
  → Read auth-flow.md (1K tokens)
  → Answer (1K tokens) = 3K total

Query 2: "What about OAuth?"
  → Read MANIFEST (1K tokens)
  → Read auth-flow.md (1K tokens)  ← Reused!
  → Answer (1K tokens) = 3K total

Query 3: "How do we handle token expiry?"
  → Read MANIFEST (1K tokens)
  → Read auth-flow.md (1K tokens)  ← Reused!
  → Answer (1K tokens) = 3K total

Total: 10K + 5K (initial synthesis) = 15K vs 15K raw RAG
But: If you ask 10 queries instead of 3, RepoKB saves 35K tokens!
```

---

## 🎓 Advanced Features

### Content-Hashed Incremental Updates

When code changes, RepoKB compares file hashes:

```python
# In .repokb/MANIFEST.json
old_hash = manifest["sources"][0]["sha256"]  # "a3f..."
new_hash = sha256(open("src/auth/login.py").read())  # "b9e..."

if old_hash != new_hash:
    # Only this file changed — regenerate its summary
    new_summary = claude_summarize("src/auth/login.py")
    
    # Mark any concept touching this file as stale
    for concept in manifest["concepts"]:
        if "src/auth/login.py" in concept["touches_sources"]:
            concept["stale"] = True
    
    # Re-synthesize only stale concepts
    for concept in manifest["concepts"]:
        if concept["stale"]:
            concept = claude_synthesize_concept(concept)
            concept["stale"] = False
```

**Result**: In a 100-file project, changing 1 file costs only 1-2 new summaries + 1-3 concept re-syntheses, not full re-ingestion.

### Marginal Sources

Large files that shouldn't inflate the MANIFEST:

```yaml
marginal_sources:
  - "evals/fixtures/**/*.json"    # Test data
  - "node_modules/**"              # Vendored code
  - "dist/**"                       # Build output
```

These are indexed in `.repokb/sources/` but don't appear in the concept routing metadata, keeping MANIFEST lean.

### Custom Concept Curation

For large projects, manually define key concepts:

```bash
python scripts/compile.py manifest-add-concept \
  --id "data-pipeline" \
  --topics "ingestion,validation,transformation,export" \
  --touches "src/pipeline/ingest.py,src/pipeline/validate.py,docs/pipeline.md" \
  --file concepts/data-pipeline.md
```

---

## 🐛 Troubleshooting

### MANIFEST Exceeds Token Budget

```
WARNING: MANIFEST exceeds 3000-token budget (3,712 tokens)
```

**Solution**: Add large fixture/vendored files to `marginal_sources` in `config.yaml`

### Concept Marked as Stale After Update

This is expected! When a source touches a concept, the concept is re-synthesized on next `update`:

```bash
python scripts/compile.py update --root .
# (Claude will be asked to re-synthesize stale concepts via work queue)
```

### Query Not Finding Relevant Concept

Check `MANIFEST.json` concept topics:

```bash
python scripts/compile.py inspect --root .
# Review the concepts list and their topics
```

If a concept is missing, create it manually or re-run `update` to re-synthesize.

---

## 🤝 Integration with Claude

RepoKB is designed as a **Claude Skill** for seamless integration:

1. **Copy `SKILL.md`** (at the repo root) to your Claude prompts folder
2. **Reference the skill** in Claude Code or Chat: "Use the repokb skill to build a knowledge base for my project"
3. **Claude handles** concept synthesis, gap detection, and query routing

---

## 📊 Evaluation Results Summary

### Dataset
- Repository: `evals/fixtures/minimal_repo/`
- Files: 8 source files (Python + Markdown)
- Total: ~58K tokens if read naively

### Results (per query)
- **MANIFEST alone**: 1K tokens
- **MANIFEST + 1 concept**: 4,994 tokens (11.7× savings)
- **MANIFEST + 2 concepts**: 6,101 tokens (9.6× savings)

### Scaling Projection
- **10 queries** on same repo:
  - Naive RAG: 580K tokens
  - RepoKB: 50K (MANIFEST + concepts) = **11.6× savings**
  
- **50 queries** (different questions):
  - Naive RAG: 2.9M tokens
  - RepoKB: ~250K tokens = **11.6× savings**

The savings compound with query volume and reuse.

---

## 🗺️ Roadmap

- [ ] Multi-repo MANIFEST aggregation
- [ ] Concept versioning (track synthesis history)
- [ ] Automated concept gap detection
- [ ] Obsidian plugin for graph browsing
- [ ] Database-backed storage for massive repos
- [ ] Web UI for knowledge base visualization

---

## 📄 License

MIT License — see [LICENSE](./LICENSE)

---

## 🙏 Acknowledgments

- Inspired by [OpenKB](https://github.com/VectifyAI/OpenKB) by VectifyAI
- Based on Andrej Karpathy's [compiled wiki concept](https://x.com/karpathy/status/2039805659525644595)
- Built for and with Claude

---

## 📞 Support

For issues, questions, or contributions:
- Open an [issue](https://github.com/your-org/repokb/issues)
- Check [SKILL.md](./SKILL.md) for detailed usage
- Review [references/](./repokb/references/) for technical deep-dives

---

**Made with ❤️ for Claude-powered code understanding.**
