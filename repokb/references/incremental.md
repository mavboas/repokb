# Incremental Update Protocol

Loaded when running `update`. This is where the token-efficiency story lives — the goal is to make routine updates cost ~10% of what the initial `init` cost.

## The diff algorithm

`scripts/compile.py update` performs this exact sequence:

1. **Walk** the repo with the same include/exclude rules as `init` (stored in `config.yaml`)
2. **Hash** every current file (sha256, streamed)
3. **Diff** against `MANIFEST.json.sources`:
   - `added` — path exists now, not in manifest
   - `removed` — in manifest, not on disk
   - `modified` — both, but sha256 differs
   - `renamed` — sha256 matches an existing entry but path differs (detected by hash-index lookup)
   - `unchanged` — both match (the silent majority)
4. **Re-extract signatures** for added + modified code files. For each, compute the new `sig_sha256` (a structural hash of the skeleton — not the file). When the modified file's `sig_sha256` is **unchanged** (body-only edit), the script marks the file as `body-only-skipped` and **emits no LLM job at all** for that file.
5. **Cascade staleness** — for each genuinely-changed source (added + modified-with-sig-change), find all concepts where `touches_sources` contains that path. Mark them `stale: true`. Body-only edits do NOT cascade.
6. **Emit summary / summarize_signature jobs** only for added + modified-with-sig-change (renames just update the path in MANIFEST, no re-summarization)
7. **Emit concept refresh jobs** only for stale concepts. Each job carries a `directive_updates` map computed from the new signatures, so the host LLM can re-anchor `<<source:>>` directives without re-discovering line ranges.

## What the host LLM actually does

For a typical update with 3 changed files affecting 2 concepts (with 1 of those 3 being a body-only edit):

1. Wait for script to finish hashing, diffing, and re-extracting signatures — it prints the delta summary
2. Process 2 worker jobs (read 2 signature skeletons + write 2 enriched summaries) — bounded cost; the body-only edit was skipped entirely
3. Process 2 concept refresh jobs (read 2 concept pages + the relevant summaries; update directive ranges from the `directive_updates` map) — bounded cost
4. Done

**Total tokens consumed:** roughly `2 × signature_size + 2 × concept_size + summary_overhead`. For a repo with 200 files where 3 changed (1 body-only), this is ~2-3% of an `init` run — and zero if all changes are body-only.

## Rename detection details

The script builds a hash → path index from the old MANIFEST. When walking the new state:
- If a path is missing but its old sha256 appears at a new path → rename
- If a path is missing and the sha256 appears nowhere → genuine delete
- If a new path's sha256 was not in the old index → genuine add

Renames update `MANIFEST.sources[i].path` and the concept's `touches_sources` entries, but do **not** trigger re-summarization. The summary file on disk is also renamed (the summary's frontmatter `source:` field is updated).

If you see a rename misclassified as delete+add (because the file's content also changed slightly), it's safe — the concept gets refreshed either way. Slight inefficiency, no correctness issue.

## Handling deletions

When a source is removed:
- Its summary file is deleted
- It's removed from `MANIFEST.sources`
- Concepts that referenced it are marked stale
- During concept refresh, you must **remove references to the deleted source** from the concept page (citations, wikilinks, sections that were entirely about that file)

If a concept's `touches_sources` becomes empty after deletions, **delete the concept** rather than refreshing it. The script will prompt you to confirm.

## Concurrency and partial updates

If `update` is interrupted (user Ctrl-C, crash), the work queue persists on disk. Re-running `update` resumes from where it left off — pending jobs in `.work_queue.jsonl` are reprocessed, completed ones in `.work_queue.results.jsonl` are skipped.

Never edit `MANIFEST.json` by hand mid-update. Use the script's helpers (`manifest-set-stale`, `manifest-add-concept`, `manifest-remove-source`, etc.). Hand edits will likely be overwritten when the next job completes.

## The body-only-edit skip (the deepest efficiency win)

For code files where signature extraction is enabled, `sig_sha256` is a fingerprint of the file's PUBLIC SURFACE: names, signatures, docstrings, kind, unclear markers. Function-body edits that don't touch any of those produce **the same fingerprint**, and the script skips both the worker job AND the cascade. For day-to-day work (tweaking implementations without changing APIs), this means *zero* LLM cost per `update`.

To see this in action: edit a function body but leave its signature and docstring alone, run `update`, and watch the "body-only edits skipped" count. The `defer_to_source` escape hatch (see `signatures.md`) is the reverse: when the LLM judges that the skeleton was insufficient, it sets `defer_to_source: true` and the script re-queues the file as a legacy `summarize` job. That defer rate is tracked in MANIFEST stats and surfaced by lint PERF-04.

## When to escalate to full re-compile

Rare, but: if the user makes a sweeping architectural change (renames every module, restructures the directory layout), the incremental diff may cascade staleness to most concepts, and at that point it's cleaner to:

```bash
rm -rf .repokb/concepts .repokb/summaries
python scripts/compile.py init --reuse-config
```

`--reuse-config` keeps the user's include/exclude settings from `config.yaml` so they don't have to redo the interview. This is genuinely cheaper than incrementally refreshing 80% of concepts, because the concept clustering can be re-done from scratch with the new structure.

Heuristic: if more than 60% of concepts go stale in a single update, suggest a full re-compile.
