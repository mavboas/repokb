"""Cursor IDE adapter.

Output: <repo_root>/.cursor/rules/repokb.mdc. Cursor's `.mdc` files have
frontmatter (description, globs, alwaysApply) and body. We replace the whole
file (it's RepoKB's rule, not the user's) and prepend the critical banner.
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


_MDC_FRONTMATTER = """---
description: RepoKB knowledge base protocol — query a compiled, token-efficient KB before reading raw source.
globs: ["**/*"]
alwaysApply: true
---
"""


class CursorAdapter(Adapter):
    name = "cursor"
    display = "Cursor"
    output_path_rel = ".cursor/rules/repokb.mdc"
    convention_version = "2025-12"
    merge_mode = "replace"
    incorporates_banner = True   # frontmatter must come first; banner inserted after
    critical_banner = (
        "**CRITICAL: Do NOT load full source files when a concept contains "
        "`<<source:>>` directives. Use your file-read tool with offset+limit "
        "to load only the cited line ranges.**"
    )

    def _default_invocation_hint(self) -> str:
        return ("This rule applies whenever you work in this repository.")

    def transform(self, parsed: ParsedCanonical, ctx: RenderContext) -> str:
        body = compile_mod.render_for_tool(parsed.raw, "cursor", {
            "TOOL_NAME": ctx.tool,
            "TOOL_DISPLAY": ctx.tool_display,
            "INVOCATION_HINT": ctx.invocation_hint,
            "MAX_CONCEPT_TOKENS": ctx.max_concept_tokens,
            "MANIFEST_TOKEN_CAP": ctx.manifest_token_cap,
            "SKILL_VERSION": ctx.skill_version,
        })
        return _MDC_FRONTMATTER + "\n" + self.critical_banner + "\n\n" + body
