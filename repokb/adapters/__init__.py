"""Per-tool adapter generation for RepoKB.

The canonical skill spec lives at `SKILL.md` (repo root). Each adapter renders
that canonical text into a tool-native instruction file (Claude SKILL.md,
Codex AGENTS.md, Copilot custom-instructions, Cursor MDC rules) so a
single source of truth drives every supported coding assistant.

The deterministic orchestrator (`repokb/scripts/compile.py`) imports
ADAPTERS from `.registry` and dispatches by tool name.
"""
from .base import Adapter

__all__ = ["Adapter", "ADAPTERS", "get_adapter"]


def __getattr__(name):
    # Lazy load the registry so importing the package doesn't force every
    # adapter class to exist yet (helps incremental development + tests).
    if name in ("ADAPTERS", "get_adapter"):
        from . import registry
        return getattr(registry, name)
    raise AttributeError(f"module 'repokb.adapters' has no attribute {name!r}")
