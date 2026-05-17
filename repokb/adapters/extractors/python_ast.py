"""Python signature extractor using the stdlib `ast` module.

Walks the module AST collecting top-level FunctionDef, AsyncFunctionDef,
ClassDef (with method children), and UPPER_SNAKE_CASE constants. Emits
<<unclear: reason>> markers when the signature alone is unlikely to convey
intent — those (and only those) symbols warrant the host LLM reading the
source.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from .base import SignatureExtractor, Symbol, Skeleton, UnclearReason

LONG_BODY_LINES = 50
COMPLEXITY_THRESHOLD = 10
USER_TAG_EXPLAIN = re.compile(r"#\s*REPOKB:\s*explain", re.IGNORECASE)
USER_TAG_FULL = re.compile(r"#\s*REPOKB:\s*full-summary", re.IGNORECASE)


class PythonAstExtractor(SignatureExtractor):
    name = "ast"
    language = "python"

    @staticmethod
    def supports(language: str, file_ext: str) -> bool:
        return language == "python" or file_ext.lower().lstrip(".") == "py"

    def extract(self, path: Path, source_rel: str) -> Skeleton:
        text = path.read_text(encoding="utf-8", errors="replace")
        full_summary = bool(USER_TAG_FULL.search(text))
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # Bad source — return empty skeleton; cmd_init falls back to LLM.
            return Skeleton(
                source_rel=source_rel, language="python", extractor="ast",
                module_docstring=None, symbols=[],
                full_summary_requested=full_summary,
            )

        module_doc = ast.get_docstring(tree)
        explain_lines = self._explain_marker_lines(text)
        symbols: list[Symbol] = []

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(self._extract_function(node, text, explain_lines))
            elif isinstance(node, ast.ClassDef):
                symbols.append(self._extract_class(node, text, explain_lines))
            elif isinstance(node, ast.Assign):
                const = self._extract_constant(node)
                if const is not None:
                    symbols.append(const)

        return Skeleton(
            source_rel=source_rel,
            language="python",
            extractor="ast",
            module_docstring=module_doc,
            symbols=symbols,
            full_summary_requested=full_summary,
        )

    @staticmethod
    def _explain_marker_lines(text: str) -> set[int]:
        return {
            i + 1
            for i, line in enumerate(text.splitlines())
            if USER_TAG_EXPLAIN.search(line)
        }

    @classmethod
    def _extract_function(
        cls, node: ast.FunctionDef | ast.AsyncFunctionDef,
        text: str, explain_lines: set[int],
    ) -> Symbol:
        sig = cls._format_signature(node)
        doc = ast.get_docstring(node)
        unclear: list[UnclearReason] = []

        body_len = (node.end_lineno or node.lineno) - node.lineno
        if not doc and body_len > LONG_BODY_LINES:
            unclear.append(UnclearReason.LOW_DOCSTRING_COVERAGE)
        if cls._cyclomatic_complexity(node) > COMPLEXITY_THRESHOLD:
            unclear.append(UnclearReason.HIGH_COMPLEXITY)
        if cls._has_dynamic_construct(node):
            unclear.append(UnclearReason.DYNAMIC_CONSTRUCT)
        if cls._has_opaque_decorator(node):
            unclear.append(UnclearReason.DECORATOR_OPAQUE)
        if any(node.lineno <= ln <= (node.end_lineno or node.lineno)
               for ln in explain_lines):
            unclear.append(UnclearReason.USER_TAGGED)

        return Symbol(
            name=node.name,
            kind="function",
            signature=sig,
            docstring=doc,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            unclear=unclear,
        )

    @classmethod
    def _extract_class(
        cls, node: ast.ClassDef, text: str, explain_lines: set[int],
    ) -> Symbol:
        bases = ", ".join(
            ast.unparse(b) if hasattr(ast, "unparse") else "..." for b in node.bases
        )
        signature = f"({bases})" if bases else ""
        doc = ast.get_docstring(node)
        children: list[Symbol] = []
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method = cls._extract_function(sub, text, explain_lines)
                method.kind = "method"
                children.append(method)

        return Symbol(
            name=node.name,
            kind="class",
            signature=signature,
            docstring=doc,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            children=children,
        )

    @staticmethod
    def _extract_constant(node: ast.Assign) -> Symbol | None:
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        name = node.targets[0].id
        if not name.isupper() or "_" not in name and len(name) < 4:
            # Heuristic: UPPER_SNAKE_CASE or at least UPPER + length>=4
            if not (name.isupper() and len(name) >= 4):
                return None
        try:
            value_repr = ast.unparse(node.value) if hasattr(ast, "unparse") else "..."
        except Exception:
            value_repr = "..."
        if len(value_repr) > 80:
            value_repr = value_repr[:77] + "..."
        return Symbol(
            name=name,
            kind="constant",
            signature=f"= {value_repr}",
            docstring=None,
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
        )

    @staticmethod
    def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        try:
            args = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
        except Exception:
            args = "..."
        returns = ""
        if node.returns is not None:
            try:
                returns = f" -> {ast.unparse(node.returns)}"
            except Exception:
                returns = ""
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        return f"{prefix}({args}){returns}"

    @staticmethod
    def _cyclomatic_complexity(node: ast.AST) -> int:
        count = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                                  ast.Try, ast.With, ast.AsyncWith)):
                count += 1
            elif isinstance(child, ast.BoolOp):
                count += len(child.values) - 1
            elif isinstance(child, ast.comprehension):
                count += 1
        return count

    @staticmethod
    def _has_dynamic_construct(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id in ("eval", "exec"):
                    return True
                if child.func.id == "getattr" and len(child.args) >= 2:
                    second = child.args[1]
                    if isinstance(second, ast.Constant) and isinstance(second.value, str):
                        return True
        return False

    @staticmethod
    def _has_opaque_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        SAFE = {"property", "staticmethod", "classmethod", "abstractmethod",
                "cached_property", "dataclass"}
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in SAFE:
                continue
            if isinstance(dec, ast.Attribute) and dec.attr in SAFE:
                continue
            # Anything else: opaque
            return True
        return False
