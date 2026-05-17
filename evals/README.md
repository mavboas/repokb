# RepoKB evals

Deterministic Python tests for the orchestrator at `repokb/scripts/compile.py`.
No LLM calls, no external dependencies — `unittest` from the stdlib.

## Run

From the project root:

```
python -m unittest discover evals -v
```

Python 3.10+ is required (the script uses `list[dict]`-style PEP 604 annotations).

## What's covered

| File | Targets |
|---|---|
| `test_walk.py` | `walk_sources`, `sha256_file`, `matches_any`, `summary_filename` — include/exclude globs, binary skip, path format, deterministic hashing |
| `test_diff.py` | `diff_sources` — added/removed/modified/unchanged + rename-by-hash detection |
| `test_manifest.py` | `empty_manifest`, `recompute_stats`, `estimate_tokens`, `Layout`, `save_manifest` 3000-token budget warning |
| `test_queue.py` | `queue_append` (JSONL format, job_id uniqueness), `queue_clear` |
| `test_lint.py` | All 8 emitted rules: STRUCT-01/04/05/06, PERF-01/02/03, KNOW-01. Each driven by a hand-built fixture MANIFEST. |
| `test_cmd_init.py` | `compile.py init` end-to-end: directory creation, MANIFEST contents, queued summary + concept_init jobs |
| `test_cmd_update.py` | `compile.py update` — staleness cascade, rename pathway (summary file gets renamed on disk, not re-summarized), delete pathway, add pathway |
| `test_cmd_helpers.py` | `manifest-add-concept`, `manifest-set-stale`, `manifest-remove-source`, `prune-orphan-summary` |

## Fixtures

- `fixtures/minimal_repo/` — 8 source files (`src/auth/*`, `src/db/*`, `tests/*`, `docs/*`) used as the input tree for init/update integration tests.
- `fixtures/manifests/*.json` — 8 pre-built MANIFESTs, each crafted to trip one specific lint rule. PERF-02 and PERF-03 fixtures also incidentally trigger PERF-01 (their construction inflates the manifest); the tests assert the target rule fires but do not assert nothing else does.

## What's NOT covered

- LLM behavior: summarization quality, concept clustering, query routing, token efficiency under real API calls. That's a separate eval layer (out of scope for this suite).
- Performance / benchmarks.
- CI integration. Wiring this into `.github/workflows/` is a one-file follow-up.

## Adding a test

1. Pure functions: import from `_support` and call directly.
   ```python
   from evals._support import compile_mod
   result = compile_mod.diff_sources(old, new)
   ```
2. Commands: use the `run_compile` subprocess helper.
   ```python
   from evals._support import run_compile, make_temp_repo
   tmp = make_temp_repo()
   run_compile("init", "--root", str(tmp))
   ```
3. Lint rules: add a hand-built fixture under `fixtures/manifests/` and a test case in `test_lint.py` that loads it via `_install_fixture_manifest`.
