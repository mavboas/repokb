"""OpenAI Codex CLI adapter.

Output: <repo_root>/AGENTS.md. Codex CLI reads AGENTS.md from the repo root
as project-level guidance. Uses sentinel merge so users can hand-write extra
guidance above/below RepoKB's block.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import compile as compile_mod  # noqa: E402

from .base import Adapter, ParsedCanonical, RenderContext


class CodexAdapter(Adapter):
    name = "codex"
    display = "OpenAI Codex CLI"
    output_path_rel = "AGENTS.md"
    convention_version = "2025-10"
    merge_mode = "sentinel"
    critical_banner = (
        "**CRITICAL: Do NOT load full source files when a concept contains "
        "`<<source:>>` directives. Use your file-read tool with offset+limit "
        "to load only the cited line ranges.**"
    )

    def _default_invocation_hint(self) -> str:
        return ("Follow this protocol whenever the user references this "
                "repository or asks you to compile/query its knowledge base.")

    def transform(self, parsed: ParsedCanonical, ctx: RenderContext) -> str:
        body = compile_mod.render_for_tool(parsed.raw, "codex", {
            "TOOL_NAME": ctx.tool,
            "TOOL_DISPLAY": ctx.tool_display,
            "INVOCATION_HINT": ctx.invocation_hint,
            "MAX_CONCEPT_TOKENS": ctx.max_concept_tokens,
            "MANIFEST_TOKEN_CAP": ctx.manifest_token_cap,
            "SKILL_VERSION": ctx.skill_version,
        })
        return body
