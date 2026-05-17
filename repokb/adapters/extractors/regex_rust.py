"""Rust signature extractor via regex.

Captures the public surface:
  - `pub fn name(...) -> ...` / `pub async fn name(...)`
  - `pub struct Name { ... }` / `pub struct Name;`
  - `pub enum Name { ... }`
  - `pub trait Name { ... }`
  - `impl ... { ... }` blocks (so impl methods get noted as part of the impl)
  - `pub const NAME: T = ...`

Private items (no `pub`) are skipped — the skeleton is for public-API
documentation, and exposing private symbols inflates the manifest.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import SignatureExtractor, Symbol, Skeleton

_FN = re.compile(
    r"^(?P<pub>pub(?:\([^)]*\))?\s+)?(?P<async>async\s+)?fn\s+"
    r"(?P<name>[A-Za-z_][\w]*)\s*(?:<[^>]*>)?\s*\((?P<args>[^)]*)\)"
    r"(?:\s*->\s*(?P<ret>[^\{\n]+))?",
    re.MULTILINE,
)
_STRUCT = re.compile(
    r"^pub(?:\([^)]*\))?\s+struct\s+(?P<name>[A-Za-z_][\w]*)",
    re.MULTILINE,
)
_ENUM = re.compile(
    r"^pub(?:\([^)]*\))?\s+enum\s+(?P<name>[A-Za-z_][\w]*)",
    re.MULTILINE,
)
_TRAIT = re.compile(
    r"^pub(?:\([^)]*\))?\s+trait\s+(?P<name>[A-Za-z_][\w]*)",
    re.MULTILINE,
)
_CONST = re.compile(
    r"^pub(?:\([^)]*\))?\s+const\s+(?P<name>[A-Z][A-Z0-9_]+)\s*:\s*[^=]+=\s*(?P<value>[^;\n]+)",
    re.MULTILINE,
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _brace_end_line(text: str, start_offset: int) -> int:
    brace_pos = text.find("{", start_offset)
    if brace_pos == -1:
        return _line_of(text, start_offset)
    depth = 0
    i = brace_pos
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return _line_of(text, i)
        i += 1
    return _line_of(text, start_offset)


class RustRegexExtractor(SignatureExtractor):
    name = "regex"
    language = "rust"

    @staticmethod
    def supports(language: str, file_ext: str) -> bool:
        return language == "rust" or file_ext.lower().lstrip(".") == "rs"

    def extract(self, path: Path, source_rel: str) -> Skeleton:
        text = path.read_text(encoding="utf-8", errors="replace")
        symbols: list[Symbol] = []

        for m in _FN.finditer(text):
            if not m.group("pub"):
                continue   # private
            start = _line_of(text, m.start())
            end = _brace_end_line(text, m.end())
            prefix = "pub "
            if m.group("async"):
                prefix += "async "
            args = m.group("args").strip()
            ret = (m.group("ret") or "").strip()
            sig = f"{prefix}fn ({args})"
            if ret:
                sig += f" -> {ret}"
            symbols.append(Symbol(
                name=m.group("name"), kind="function", signature=sig,
                docstring=None, start_line=start, end_line=end,
            ))

        for pattern, kind in [(_STRUCT, "struct"), (_ENUM, "enum"), (_TRAIT, "trait")]:
            for m in pattern.finditer(text):
                start = _line_of(text, m.start())
                end = _brace_end_line(text, m.end())
                symbols.append(Symbol(
                    name=m.group("name"), kind=kind, signature="",
                    docstring=None, start_line=start, end_line=end,
                ))

        for m in _CONST.finditer(text):
            start = _line_of(text, m.start())
            value = m.group("value").strip()
            if len(value) > 60:
                value = value[:57] + "..."
            symbols.append(Symbol(
                name=m.group("name"), kind="constant", signature=f"= {value}",
                docstring=None, start_line=start, end_line=start,
            ))

        symbols.sort(key=lambda s: s.start_line)
        return Skeleton(
            source_rel=source_rel, language="rust", extractor="regex",
            module_docstring=None, symbols=symbols,
        )
