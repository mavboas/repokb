# Scaling to Large Repos

Loaded when the user has a monorepo, when `stats.concepts > 80`, or when lint emits PERF-02.

## The problem

The default flat MANIFEST works beautifully up to ~80 concepts and ~500 sources. Beyond that:
- MANIFEST exceeds its 3000-token budget
- Routing accuracy degrades (too many similar topic phrases to disambiguate)
- Concept refresh during update slows down because the staleness cascade hits more nodes

## Solution: nested topic indexing

Introduce a `topics/` layer between MANIFEST and concepts. The MANIFEST lists **topics** (10-20 broad areas), and each topic has its own sub-manifest listing concepts.

```
.repokb/
├── MANIFEST.json          Lists topics, not concepts
├── topics/
│   ├── auth.json          Sub-manifest: concepts in this topic
│   ├── data-pipeline.json
│   └── deployment.json
├── concepts/              Same as before
└── summaries/
```

### Routing flow (two-hop)

1. Read `MANIFEST.json` → 10-20 topic entries with broad descriptions
2. Pick the 1-2 topics matching the question
3. Read those topics' sub-manifests → concept lists scoped to the topic
4. Pick 1-2 concepts and read them

Total tokens for a typical query: MANIFEST (1500) + 1 topic sub-manifest (800) + 1 concept (1200) ≈ 3500. Comparable to flat mode despite handling 5× more concepts.

## When to migrate

The script can migrate automatically:

```bash
python scripts/compile.py migrate-to-nested --root .
```

Run this when:
- `lint` emits PERF-02 (too many concepts)
- The user reports that routing feels imprecise (Claude loads the wrong concept frequently)
- The repo crosses a domain boundary (e.g., a monorepo with backend + frontend + infra)

The migration:
1. Clusters existing concepts into topics by analyzing `related_concepts` and `topics` overlap
2. Proposes a topic structure for user approval
3. Generates topic sub-manifests
4. Updates MANIFEST to reference topics instead of concepts directly

This is irreversible without manual cleanup, so always confirm with the user before running.

## Don't pre-emptively scale

For repos under ~80 concepts, the flat structure is **strictly better** — less indirection, faster routing, simpler debugging. Don't migrate "just in case". The complexity cost of nesting is real, and small repos don't pay it back.
