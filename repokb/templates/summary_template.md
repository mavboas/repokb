<!--
  This is the template for `summarize` jobs (prose/markdown/uncategorized
  files where signature extraction does not apply).

  For CODE files where the script emits `summarize_signature` jobs, use
  `signature_summary_template.md` instead — that template skips the symbol
  list (the skeleton has it) and only asks for Purpose + Notable decisions.
-->
---
source: <relative/path/to/source>
sha256: <full sha256>
type: <python | typescript | markdown | yaml | ...>
tags: [<tag1>, <tag2>]   # max 5
bytes: <int>
mtime: <ISO8601>
---

# Purpose

One sentence on what this file does in the system. Be concrete: "Implements OAuth callback handler" beats "Auth-related code".

# Key symbols

Bullet list of top-level exports / public surface. For each:
- name, signature (briefly), one-line description

Skip implementation details. The concept page is where mechanism lives. This file is for **lookup**: "what's in this file" should be answerable from the summary alone.

# External contracts

- Reads from: <data sources, modules imported for behavior, env vars>
- Writes to: <return surfaces, side effects>
- Depends on: <key internal modules, with one-line reason>

# Notable decisions / gotchas

Brief notes on non-obvious choices, TODO/HACK comments worth surfacing, performance considerations, security-sensitive sections. Cite by line range.

<!--
  Budget: 200-400 tokens. Hard ceiling 400 (script will warn if exceeded).
  Never quote code blocks longer than 5 lines. Use "lines X-Y do Z" form.
  Never list all imports verbatim.
-->
