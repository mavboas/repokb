---
id: <kebab-case-id>
topics:
  - <specific phrase 1>
  - <specific phrase 2>
  - <specific phrase 3>
touches_sources:
  - <relative/path/to/source1>
  - <relative/path/to/source2>
related_concepts:
  - <other-concept-id>
last_synthesized: <ISO8601>
gaps: []
---

# <Concept Title>

<!--
  Length budget: aim for 800-1500 tokens total. If you exceed 1500, split.
  Audience: a developer who knows the language/stack but not this specific codebase.
  Style: explanatory prose with code references by line range, not large code blocks.
-->

## Summary

One paragraph (3-5 sentences) answering: what is this concept, why does it exist, and what is its scope? Read this and the reader should know whether to keep reading or look elsewhere.

## How it works

Walk through the mechanism in PROSE, with inline `<<source:>>` directives so the host LLM can pull exact line ranges only when verbatim code is needed. **Prefer prose-with-citation over fenced code blocks** — pasting code into the concept defeats the whole point of the directive protocol.

- Credentials are validated using bcrypt with a constant-time compare at `<<source: src/auth/login.py:42-67>>`.
- Tokens are issued with a 1h TTL and carry `user_id`/`role` claims; the issuer lives at `<<source: src/auth/jwt.py:18-30>>`.
- Every request runs through the middleware at `<<source: src/middleware/auth.py:55-90>>`, which validates the token and attaches the user to `request.state.user`.

Use diagrams sparingly — a small mermaid sequence diagram earns its tokens for non-trivial flows, but skip for simple ones.

## Key decisions

Bullet list of non-obvious design choices and the reasoning behind them. Cite the source where the decision is encoded (commit message, code comment, ADR doc).

- **Bcrypt cost 12** — chosen over argon2 because of legacy hashes; migration path documented in [[migration-plan]]
- **JWT in cookie, not header** — anti-XSS, paired with CSRF token

## Edge cases and gotchas

Things that have bitten developers or will. Pull from comments tagged TODO/HACK/XXX, from test names that hint at past bugs, from ADRs.

## Related concepts

- [[error-handling]] — how auth failures propagate to HTTP responses
- [[data-model]] — user and session tables referenced here

## Gaps

<!--
  When you find something this concept *should* answer but the sources don't cover,
  add a frontmatter gap entry AND mention it here so the user sees it.
  Format:
    gaps:
      - description: "no docs explain why session TTL is 1h not 24h"
        since: 2026-05-16
-->

<!-- Contradictions (if any) go here as inline HTML comments:
     <!-- contradiction: docs say port 8080, code uses 8000 (src/server.py:12) -->
-->
