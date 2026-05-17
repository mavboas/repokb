"""GitHub Copilot adapter.

Output: <repo_root>/.github/copilot-instructions.md. Copilot's context window
is tight, so we aggressively trim sections that Codex/Claude keep. The
critical banner is still prepended at the top, and we keep the workflow +
MANIFEST contract + directive protocol — which is the load-bearing content.

Sections dropped (vs canonical):
  - Failure modes (purely advisory)
  - Quick reference token budget targets (referenced via Manifest contract)
  - Concept page format (style guide; Copilot mostly consumes, doesn't write)
  - Non-goals (defensive; not needed when Copilot is the audience)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import compile as compile_mod  # noqa: E402

from .base import Adapter, ParsedCanonical, RenderContext

# Sections to drop, identified by their `## ` heading text. Matched against
# the heading line only; the section runs until the next `## ` or end of file.
_DROP_SECTIONS = (
    "Non-goals and explicit limits",
    "Failure modes to watch for",
    "Quick reference: token budget targets",
    "Concept page format",
)
_TOKEN_BUDGET = 3000


class CopilotAdapter(Adapter):
    name = "copilot"
    display = "GitHub Copilot"
    output_path_rel = ".github/copilot-instructions.md"
    convention_version = "2025-11"
    merge_mode = "sentinel"
    critical_banner = (
        "**CRITICAL: Do NOT load full source files when a concept contains "
        "`<<source:>>` directives. Use your file-read tool with offset+limit "
        "to load only the cited line ranges.**"
    )

    def _default_invocation_hint(self) -> str:
        return ("Follow this protocol whenever you answer questions about "
                "this repository.")

    def transform(self, parsed: ParsedCanonical, ctx: RenderContext) -> str:
        body = compile_mod.render_for_tool(parsed.raw, "copilot", {
            "TOOL_NAME": ctx.tool,
            "TOOL_DISPLAY": ctx.tool_display,
            "INVOCATION_HINT": ctx.invocation_hint,
            "MAX_CONCEPT_TOKENS": ctx.max_concept_tokens,
            "MANIFEST_TOKEN_CAP": ctx.manifest_token_cap,
            "SKILL_VERSION": ctx.skill_version,
        })
        body = _drop_sections(body, _DROP_SECTIONS)

        # Soft budget check (warn but don't truncate — truncating would lie).
        approx_tokens = compile_mod.estimate_tokens(body)
        if approx_tokens > _TOKEN_BUDGET:
            sys.stderr.write(
                f"WARNING: Copilot instructions exceed {_TOKEN_BUDGET}-token "
                f"budget ({approx_tokens} tokens). Consider trimming the "
                "canonical SKILL.md or adding more sections to _DROP_SECTIONS.\n"
            )
        return body


_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _drop_sections(text: str, headings: tuple[str, ...]) -> str:
    """Remove `## Heading` ... up to the next `## ` (or EOF) for each match."""
    out = text
    for heading in headings:
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}\s*$.*?(?=^##\s+|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        out = pattern.sub("", out)
    # Collapse any 3+ blank lines we created.
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out
