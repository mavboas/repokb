# Compilation Protocol

This reference is loaded when running `init` or when a query's required concept doesn't exist and must be synthesized on demand.

## The two-phase protocol

The script (`scripts/compile.py`) handles **deterministic** work — walking the filesystem, hashing, file I/O, MANIFEST maintenance, AST/regex signature extraction. The host LLM (Claude / Codex / Copilot / Cursor — whichever is running this skill) handles **non-deterministic** work — summary enrichment and concept synthesis. The split matters: it keeps the script reliable and minimizes the LLM tokens spent on plumbing.

The script communicates with the host LLM via a **work queue**: a temp file `.repokb/.work_queue.jsonl` where each line is a job. The host LLM reads the queue, does the work, writes outputs to the paths the script tells it, then marks the job done.

### Phase 1: Per-source summarization (two job kinds)

For each new or modified source file the script emits ONE of two jobs:

**Job kind A — `summarize_signature` (code files with enabled extractors):**

```json
{"job": "summarize_signature", "source_path": "src/auth/login.py",
 "out_path": ".repokb/summaries/src__auth__login.py.md",
 "signature_path": ".repokb/signatures/src__auth__login.py.md",
 "sha256": "a3f...", "sig_sha256": "b9e..."}
```

The host LLM reads **only the signature skeleton** (a deterministic, AST-derived map of public symbols + docstrings + `<<source:>>` directives + `<<unclear: reason>>` markers — see `signatures.md`). It enriches with just `Purpose` (1 sentence) + `Notable decisions / gotchas`. It does NOT read the source file unless a symbol carries `<<unclear:>>` — and then only the cited line range.

If the skeleton is fundamentally insufficient for the file, the LLM returns `{"defer_to_source": true, "reason": "..."}` and the script re-queues the file as a legacy `summarize` job.

**Job kind B — `summarize` (prose, markdown, or any file without an enabled extractor):**

```json
{"job": "summarize", "source_path": "docs/auth.md", "out_path": ".repokb/summaries/docs__auth.md.md", "sha256": "a3f..."}
```

For each `summarize` job:

1. Read the source file (the **only** time the raw file enters context)
2. Write a summary to `out_path` following the template below
3. Append a line `{"job_id": "...", "status": "done", "tags": [...], "tokens_est": N}` to `.repokb/.work_queue.results.jsonl`

**Summary template** (target: 200-400 tokens):

```markdown
---
source: src/auth/login.py
sha256: a3f...
type: python
tags: [auth, session, jwt]
---

# Purpose
One sentence on what this file does in the system.

# Key symbols
- `login(request)` — entry point, validates credentials, issues JWT
- `_check_password(hash, plain)` — constant-time comparison helper
- `SESSION_TTL` — module constant, 3600s

# External contracts
- Reads from: `users` table via `db.user_repo`
- Writes to: `sessions` table, response cookies
- Depends on: `crypto.password`, `config.jwt_secret`

# Notable decisions / gotchas
- Uses bcrypt cost 12 (intentional, see git blame)
- Returns 200 with empty body on invalid creds (timing-safe, anti-enumeration)
```

**Do not:**
- Quote large blocks of code (>5 lines). Use line ranges instead: `lines 42-67 implement X`
- Include imports list verbatim
- Speculate on intent beyond what code and adjacent comments support

For binary/structured docs (PDF, .docx, .pptx), the script pre-converts them via `markitdown` and gives you the markdown path as the source. Same summary template applies.

### Phase 2: Concept synthesis

After all summaries are written, the script emits concept jobs. Two cases:

**Case A — init (no existing concepts):**

```json
{"job": "concept_init", "summary_paths": ["...", "..."], "manifest_path": ".repokb/MANIFEST.json"}
```

You receive all summary paths and must propose a **flat list of concepts** that cover the repo. Aim for:
- **10-30 concepts** for a typical repo (50-500 files)
- Each concept synthesizing **3-15 sources**
- Topic boundaries that match how a developer would ask questions ("auth flow", "data ingestion pipeline", "deployment", "testing strategy") — NOT how directories are organized

Process:
1. Read all summaries (this is the one expensive phase, accepted because it happens once)
2. Cluster summaries by topic affinity
3. For each cluster, write a concept page using the template at `templates/concept_template.md`
4. Update MANIFEST with the new concept entries (the script provides a helper: `python scripts/compile.py manifest-add-concept --id X --topics ... --touches ...`)

**Case B — update (concepts exist, some are stale):**

```json
{"job": "concept_refresh", "concept_id": "auth-flow", "stale_reason": "src/auth/oauth.py modified", "current_path": ".repokb/concepts/auth-flow.md", "summaries_to_reread": ["..."]}
```

For each refresh job:
1. Read the current concept page (to preserve structure and prior synthesis)
2. Read **only** the summaries listed in `summaries_to_reread` (the script computed which ones changed)
3. Update the concept page in place, preserving wikilinks where still valid
4. Update its `last_synthesized` and clear `stale` in MANIFEST via the helper

**Critical efficiency rule:** never re-read sources during refresh. Summaries are the working layer for concept synthesis. If a summary is wrong, fix the summary first (Phase 1 will have already regenerated it for changed files).

## When to ask the user vs. proceed

Proceed without asking:
- File walking and ignores (use `.gitignore` + sensible defaults)
- Hash computation, MANIFEST writes
- Summary generation for unambiguous files
- Concept refresh on already-defined concepts

Ask the user:
- Initial concept boundaries — show your proposed list of concept IDs + one-line descriptions, get approval before writing them
- Whether to ingest large generated files (>1MB, lock files, minified bundles)
- When two files seem to belong to no existing concept (offer: "create new concept X, or extend concept Y?")
