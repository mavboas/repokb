"""JS/TS signature extractors via regex.

Captures the common JS/TS public surface forms:
  - `function foo(...)` and `async function foo(...)`
  - `class Foo extends Bar { ... }`
  - `export const foo = (...) => ...`
  - `export function foo(...)`
  - `export class Foo`
  - `export default function foo(...)`

Conservative by design — misses fancy patterns like decorators or
namespaced classes. When confidence drops below threshold the consumer
should fall back to the LLM summarize path; we don't try to be smart.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import SignatureExtractor, Symbol, Skeleton

# Top-level (column 0 or after `export`/`export default`)
_FUNC = re.compile(
    r"^(?P<export>export\s+(?:default\s+)?)?(?P<async>async\s+)?"
    r"function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>[^)]*)\)",
    re.MULTILINE,
)
_CLASS = re.compile(
    r"^(?P<export>export\s+(?:default\s+)?)?class\s+(?P<name>[A-Za-z_$][\w$]*)"
    r"(?:\s+extends\s+(?P<base>[A-Za-z_$][\w$.]*))?",
    re.MULTILINE,
)
_ARROW = re.compile(
    r"^(?P<export>export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?P<async>async\s+)?\((?P<args>[^)]*)\)\s*=>",
    re.MULTILINE,
)
_TS_INTERFACE = re.compile(
    r"^(?P<export>export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_TS_TYPE = re.compile(
    r"^(?P<export>export\s+)?type\s+(?P<name>[A-Za-z_$][\w$]*)\s*=",
    re.MULTILINE,
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _approx_end_line(text: str, start_offset: int, name: str) -> int:
    """Walk the brace balance from the first '{' after start_offset.

    Falls back to start+10 if no braces found (e.g., arrow with implicit return).
    """
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


class _JsLike(SignatureExtractor):
    """Shared JS/TS extraction logic; subclasses set name + language."""
    extra_patterns: list[re.Pattern] = []

    @classmethod
    def supports(cls, language: str, file_ext: str) -> bool:
        ext = file_ext.lower().lstrip(".")
        return language == cls.language or ext in cls._extensions()

    @classmethod
    def _extensions(cls) -> set[str]:
        return set()

    def extract(self, path: Path, source_rel: str) -> Skeleton:
        text = path.read_text(encoding="utf-8", errors="replace")
        symbols: list[Symbol] = []

        for m in _FUNC.finditer(text):
            start = _line_of(text, m.start())
            end = _approx_end_line(text, m.end(), m.group("name"))
            prefix = "async " if m.group("async") else ""
            symbols.append(Symbol(
                name=m.group("name"), kind="function",
                signature=f"{prefix}({m.group('args').strip()})",
                docstring=None, start_line=start, end_line=end,
            ))

        for m in _CLASS.finditer(text):
            start = _line_of(text, m.start())
            end = _approx_end_line(text, m.end(), m.group("name"))
            sig = f"extends {m.group('base')}" if m.group("base") else ""
            symbols.append(Symbol(
                name=m.group("name"), kind="class", signature=sig,
                docstring=None, start_line=start, end_line=end,
            ))

        for m in _ARROW.finditer(text):
            start = _line_of(text, m.start())
            end = _approx_end_line(text, m.end(), m.group("name"))
            prefix = "async " if m.group("async") else ""
            symbols.append(Symbol(
                name=m.group("name"), kind="function",
                signature=f"{prefix}({m.group('args').strip()})",
                docstring=None, start_line=start, end_line=end,
            ))

        for pattern in self.extra_patterns:
            for m in pattern.finditer(text):
                start = _line_of(text, m.start())
                symbols.append(Symbol(
                    name=m.group("name"), kind="type",
                    signature="", docstring=None,
                    start_line=start, end_line=start,
                ))

        symbols.sort(key=lambda s: (s.start_line, s.name))
        return Skeleton(
            source_rel=source_rel, language=self.language,
            extractor="regex", module_docstring=None, symbols=symbols,
        )


class JsRegexExtractor(_JsLike):
    name = "regex"
    language = "javascript"

    @classmethod
    def _extensions(cls):
        return {"js", "mjs", "cjs", "jsx"}


class TsRegexExtractor(_JsLike):
    name = "regex"
    language = "typescript"
    extra_patterns = [_TS_INTERFACE, _TS_TYPE]

    @classmethod
    def _extensions(cls):
        return {"ts", "tsx"}
