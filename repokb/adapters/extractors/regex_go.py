"""Go signature extractor via regex.

Captures:
  - `func Name(...) ...` (top-level functions)
  - `func (r *Recv) Name(...) ...` (methods)
  - `type Name struct { ... }` / `type Name interface { ... }`
  - `const NAME = ...` (top-level)
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import SignatureExtractor, Symbol, Skeleton

_FUNC = re.compile(
    r"^func\s+(?:\((?P<recv>[^)]+)\)\s+)?(?P<name>[A-Za-z_][\w]*)\s*"
    r"\((?P<args>[^)]*)\)\s*(?P<ret>[^\{\n]*)?",
    re.MULTILINE,
)
_TYPE = re.compile(
    r"^type\s+(?P<name>[A-Za-z_][\w]*)\s+(?P<kind>struct|interface)\b",
    re.MULTILINE,
)
_CONST = re.compile(
    r"^const\s+(?P<name>[A-Z][A-Z0-9_]+)\s*(?:[\w\[\]\*\.]+\s*)?=\s*(?P<value>[^\n]+)",
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


class GoRegexExtractor(SignatureExtractor):
    name = "regex"
    language = "go"

    @staticmethod
    def supports(language: str, file_ext: str) -> bool:
        return language == "go" or file_ext.lower().lstrip(".") == "go"

    def extract(self, path: Path, source_rel: str) -> Skeleton:
        text = path.read_text(encoding="utf-8", errors="replace")
        symbols: list[Symbol] = []

        for m in _FUNC.finditer(text):
            start = _line_of(text, m.start())
            end = _brace_end_line(text, m.end())
            recv = m.group("recv") or ""
            kind = "method" if recv else "function"
            args = m.group("args").strip()
            ret = (m.group("ret") or "").strip()
            sig = f"({args}) {ret}".rstrip()
            name = m.group("name")
            display_name = f"({recv}) {name}" if recv else name
            symbols.append(Symbol(
                name=display_name, kind=kind, signature=sig,
                docstring=None, start_line=start, end_line=end,
            ))

        for m in _TYPE.finditer(text):
            start = _line_of(text, m.start())
            end = _brace_end_line(text, m.end())
            symbols.append(Symbol(
                name=m.group("name"),
                kind="struct" if m.group("kind") == "struct" else "interface",
                signature=m.group("kind"),
                docstring=None, start_line=start, end_line=end,
            ))

        for m in _CONST.finditer(text):
            start = _line_of(text, m.start())
            value = m.group("value").strip()
            if len(value) > 60:
                value = value[:57] + "..."
            symbols.append(Symbol(
                name=m.group("name"), kind="constant",
                signature=f"= {value}",
                docstring=None, start_line=start, end_line=start,
            ))

        symbols.sort(key=lambda s: s.start_line)
        return Skeleton(
            source_rel=source_rel, language="go", extractor="regex",
            module_docstring=None, symbols=symbols,
        )
