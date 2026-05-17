"""Claude Code / claude.ai skill adapter.

Output: repokb/SKILL.md (with placeholders rendered + TOOL:claude blocks kept).
The canonical IS this file before rendering — emit-adapters writes it back to
the same location with placeholders resolved, so a fresh `git status` shows
a clean diff only when content actually changed.

Claude tolerates the full canonical prose (no token-trimming needed). YAML
frontmatter is the activation contract for Claude's skill system.
"""
from __future__ import annotations

from pathlib import Path

# Import via the script's sys.path bootstrap when invoked through compile.py
import sys
_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import compile as compile_mod  # noqa: E402  (path bootstrap)

from .base import Adapter, ParsedCanonical, RenderContext


class ClaudeAdapter(Adapter):
    name = "claude"
    display = "Claude Code"
    output_path_rel = "CLAUDE.md"
    convention_version = "2025-09"
    merge_mode = "sentinel"
    critical_banner = None

    # The canonical SKILL.md at repokb/SKILL.md is the actual Claude skill
    # (with TOOL: blocks intact). emit-adapters writes a PROJECT-LEVEL
    # CLAUDE.md to the target repo root for Claude Code to pick up as
    # project guidance — keeping the canonical untouched so the other
    # adapters can still re-render.

    def _default_invocation_hint(self) -> str:
        return ("This skill activates when the user asks Claude to compile, "
                "query, or update a repository knowledge base.")

    def transform(self, parsed: ParsedCanonical, ctx: RenderContext) -> str:
        return compile_mod.render_for_tool(parsed.raw, "claude", {
            "TOOL_NAME": ctx.tool,
            "TOOL_DISPLAY": ctx.tool_display,
            "INVOCATION_HINT": ctx.invocation_hint,
            "MAX_CONCEPT_TOKENS": ctx.max_concept_tokens,
            "MANIFEST_TOKEN_CAP": ctx.manifest_token_cap,
            "SKILL_VERSION": ctx.skill_version,
        })
