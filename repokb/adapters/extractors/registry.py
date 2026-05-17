"""Extractor registry + dispatch.

Resolves (language, file extension, config) → which extractor to run.
"""
from __future__ import annotations

from .base import SignatureExtractor

LANGUAGE_BY_EXT = {
    "py": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript",
    "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "go": "go",
    "rs": "rust",
}


def _load() -> dict[tuple[str, str], SignatureExtractor]:
    """Return (language, method) → extractor instance."""
    from .python_ast import PythonAstExtractor
    from .regex_js import JsRegexExtractor, TsRegexExtractor
    from .regex_go import GoRegexExtractor
    from .regex_rust import RustRegexExtractor
    return {
        ("python", "ast"): PythonAstExtractor(),
        ("javascript", "regex"): JsRegexExtractor(),
        ("typescript", "regex"): TsRegexExtractor(),
        ("go", "regex"): GoRegexExtractor(),
        ("rust", "regex"): RustRegexExtractor(),
    }


EXTRACTORS: dict[tuple[str, str], SignatureExtractor] = _load()


def get_extractor(language: str, method: str) -> SignatureExtractor:
    key = (language, method)
    if key not in EXTRACTORS:
        raise KeyError(f"No extractor for ({language}, {method})")
    return EXTRACTORS[key]


def choose_extractor(
    file_ext: str, signature_extraction_cfg: dict
) -> SignatureExtractor | None:
    """Resolve config + ext → extractor. None means 'fall back to LLM summarize'.

    Config example:
        signature_extraction:
          python: ast
          javascript: regex
          "*": false
    """
    lang = LANGUAGE_BY_EXT.get(file_ext.lower().lstrip("."))
    if lang is None:
        return None
    if lang in signature_extraction_cfg:
        method = signature_extraction_cfg[lang]
        if method in (None, False, "false", "off"):
            # Explicit opt-out: do NOT fall through to wildcard.
            return None
    else:
        wildcard = signature_extraction_cfg.get("*")
        if wildcard in (None, False, "false", "off"):
            return None
        method = wildcard
    return EXTRACTORS.get((lang, str(method)))
