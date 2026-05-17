"""Signature extractors.

Each extractor produces a deterministic skeleton of a source file's public
surface (functions, classes, constants, module docstrings) so the host LLM
can enrich it with intent/decisions without reading the raw source.

Priority dispatched by language (config.signature_extraction):
  1. AST  — full fidelity, language-specific (Python via stdlib)
  2. Regex — coarse, zero-dep, JS/TS/Go/Rust
  3. LLM  — fallback: the host LLM reads the full file (legacy summarize job)

Adding a new extractor: subclass SignatureExtractor, register it in
`registry.EXTRACTORS`.
"""
from .base import SignatureExtractor, Symbol, Skeleton, UnclearReason
from .registry import EXTRACTORS, get_extractor, choose_extractor

__all__ = [
    "SignatureExtractor", "Symbol", "Skeleton", "UnclearReason",
    "EXTRACTORS", "get_extractor", "choose_extractor",
]
