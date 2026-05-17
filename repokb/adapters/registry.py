"""Adapter registry. Populated lazily so import cycles stay clean."""
from __future__ import annotations

from .base import Adapter


def _load() -> dict[str, Adapter]:
    from .claude import ClaudeAdapter
    from .codex import CodexAdapter
    from .copilot import CopilotAdapter
    from .cursor import CursorAdapter
    return {
        "claude": ClaudeAdapter(),
        "codex": CodexAdapter(),
        "copilot": CopilotAdapter(),
        "cursor": CursorAdapter(),
    }


ADAPTERS: dict[str, Adapter] = _load()


def get_adapter(name: str) -> Adapter:
    if name not in ADAPTERS:
        raise KeyError(f"Unknown adapter '{name}'. Known: {sorted(ADAPTERS)}")
    return ADAPTERS[name]
