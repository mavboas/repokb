"""SignatureExtractor ABC + data classes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class UnclearReason(str, Enum):
    """Why a symbol's signature alone may not capture intent.

    Emitted into <<unclear: reason>> markers in the skeleton so the host LLM
    knows which specific symbols (and only those) warrant reading the source.
    """
    LOW_DOCSTRING_COVERAGE = "low-docstring-coverage"
    HIGH_COMPLEXITY = "high-complexity"
    DYNAMIC_CONSTRUCT = "dynamic-construct"
    USER_TAGGED = "user-tagged"          # # REPOKB: explain
    DECORATOR_OPAQUE = "decorator-opaque"


@dataclass
class Symbol:
    """A single extracted symbol: function, class, constant."""
    name: str
    kind: str                        # "function" | "class" | "constant" | "method"
    signature: str                   # e.g. "(request, user_id: int) -> Response"
    docstring: str | None
    start_line: int
    end_line: int
    unclear: list[UnclearReason] = field(default_factory=list)
    children: list["Symbol"] = field(default_factory=list)   # methods within a class


@dataclass
class Skeleton:
    """Whole-file extraction result."""
    source_rel: str                  # path relative to repo root
    language: str                    # "python" | "javascript" | ...
    extractor: str                   # "ast" | "regex" | "llm"
    module_docstring: str | None
    symbols: list[Symbol]
    full_summary_requested: bool = False   # # REPOKB: full-summary

    def all_unclear(self) -> list[tuple[Symbol, UnclearReason]]:
        out: list[tuple[Symbol, UnclearReason]] = []
        for sym in self.symbols:
            for r in sym.unclear:
                out.append((sym, r))
            for child in sym.children:
                for r in child.unclear:
                    out.append((child, r))
        return out


class SignatureExtractor(ABC):
    """Extract a Skeleton from a source file."""

    name: str            # "ast" | "regex"
    language: str        # "python" | "javascript" | "typescript" | "go" | "rust"

    @abstractmethod
    def extract(self, path: Path, source_rel: str) -> Skeleton:
        raise NotImplementedError

    @staticmethod
    def supports(language: str, file_ext: str) -> bool:
        """Subclasses override to declare file-extension match."""
        return False
