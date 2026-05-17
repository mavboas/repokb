---
source: <relative/path/to/source>
sha256: <full sha256>
type: <python | javascript | typescript | go | rust>
signature_source: <ast | regex>
sig_sha256: <full sha256 of the skeleton>
tags: [<tag1>, <tag2>]   # max 5
bytes: <int>
mtime: <ISO8601>
---

# Purpose

One sentence on what this file does in the system. Be concrete:
"Implements OAuth callback handler" beats "Auth-related code."

# Notable decisions / gotchas

Brief notes on non-obvious choices, TODO/HACK comments worth surfacing,
performance considerations, security-sensitive sections. Cite by line
range. **Do NOT restate the symbol list — the signature skeleton already
contains it.**

<!--
  Budget: 100-250 tokens (smaller than legacy summaries because the
  symbol list is in the skeleton, not here). Hard ceiling 300.

  When working on a `summarize_signature` job:
    - Read the signature file (signature_path in the job payload).
    - DO NOT read the source file unless the skeleton flags
      <<unclear: reason>> next to specific symbols.
    - If you read for an unclear marker, use your file-read tool with
      offset+limit to load ONLY that symbol's line range.
    - If the skeleton is fundamentally insufficient for this file (e.g.,
      a 300-line procedural script with no helpful structure), return
      {"defer_to_source": true, "reason": "..."} in your job result
      instead of writing a summary. The script will re-queue it as a
      regular `summarize` job.
-->
