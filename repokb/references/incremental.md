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
4. **Cascade staleness** — for each non-unchanged source, find all concepts where `touches_sources` contains that path. Mark them `stale: true`.
5. **Emit summary jobs** only for `added` and `modified` (renames just update the path in MANIFEST, no re-summarization)
6. **Emit concept refresh jobs** only for stale concepts, with `summaries_to_reread` populated from the cascade

## What you (Claude) actually do

For a typical update with 3 changed files affecting 2 concepts:

1. Wait for script to finish hashing and diffing — it prints the delta summary
2. Process 3 summary jobs (read 3 files, write 3 summaries) — bounded cost
3. Process 2 concept refresh jobs (read 2 concept pages + the relevant summaries) — bounded cost
4. Done

**Total tokens consumed:** roughly `3 × source_size + 2 × concept_size + summary_overhead`. For a repo with 200 files where 3 changed, this is ~5% of an `init` run.

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

## When to escalate to full re-compile

Rare, but: if the user makes a sweeping architectural change (renames every module, restructures the directory layout), the incremental diff may cascade staleness to most concepts, and at that point it's cleaner to:

```bash
rm -rf .repokb/concepts .repokb/summaries
python scripts/compile.py init --reuse-config
```

`--reuse-config` keeps the user's include/exclude settings from `config.yaml` so they don't have to redo the interview. This is genuinely cheaper than incrementally refreshing 80% of concepts, because the concept clustering can be re-done from scratch with the new structure.

Heuristic: if more than 60% of concepts go stale in a single update, suggest a full re-compile.
