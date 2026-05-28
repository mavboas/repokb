#!/usr/bin/env python3
"""
compile.py — RepoKB orchestrator.

Handles deterministic work: walking, hashing, MANIFEST maintenance, work queue,
AST/regex signature extraction, per-tool adapter emission.

Calls back to the host LLM (Claude / Codex / Copilot / Cursor — whichever is
running this skill) for summarization, concept synthesis, and signature
enrichment via a JSONL work queue protocol.

Usage:
    compile.py init [--root PATH] [--config-from-interview | --reuse-config]
    compile.py update [--root PATH]
    compile.py lint [--root PATH]
    compile.py inspect [--root PATH] [--directive-stats]
    compile.py emit-adapters [--root PATH] [--tools T,T,...]
                              [--dry-run | --diff-only] [--yes] [--force]
                              [--mode merge|replace]
    compile.py adapter-check [--root PATH]
    compile.py extract-signatures [--root PATH] [--paths P,P,...]
    compile.py migrate [--root PATH] [--to-version 2]
    compile.py manifest-add-concept --id ID --topics "a,b,c" --touches "p1,p2" --file PATH
    compile.py manifest-set-stale --concept ID --stale BOOL
    compile.py manifest-remove-source --path PATH
    compile.py prune-orphan-summary --path PATH

Design note:
    This script never calls an LLM. It writes work-queue jobs to
    .repokb/.work_queue.jsonl and reads results from
    .repokb/.work_queue.results.jsonl. The skill's caller (the host LLM)
    is responsible for processing the queue between script invocations.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Allow importing sibling packages (repokb.adapters.*) when invoked as a script.
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPOKB_PKG = _SCRIPT_DIR.parent
_PROJECT_ROOT = _REPOKB_PKG.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

SCHEMA_VERSION = 2
SKILL_VERSION = "v2"
DEFAULT_EXCLUDES = [
    ".git/**", "node_modules/**", "dist/**", "build/**", ".venv/**",
    "__pycache__/**", "*.pyc", ".repokb/**", ".DS_Store",
    "*.lock", "package-lock.json", "yarn.lock", "poetry.lock",
    "*.min.js", "*.min.css",
]
DEFAULT_CONFIG = {
    "include_globs": ["**/*"],
    "exclude_globs": DEFAULT_EXCLUDES,
    "ingest_binary_docs": True,
    "max_concept_tokens": 1500,
    "max_summary_tokens": 400,
    "max_concepts": 80,
    "marginal_sources": [],
    "signature_extraction": {
        "python": "ast",
        "javascript": "regex",
        "typescript": "regex",
        "go": "regex",
        "rust": "regex",
        "*": False,
    },
    "audit_directives": False,
}
BINARY_DOC_EXTS = {".pdf", ".docx", ".pptx", ".xlsx"}
CANONICAL_SKILL_PATH = _PROJECT_ROOT / "SKILL.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def estimate_tokens(text: str) -> int:
    """Rough token count; good enough for budget enforcement."""
    return max(1, len(text) // 4)


def sha256_text(text: str) -> str:
    """Hash a string; used for skeleton/canonical-skill stamping."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def summary_filename(source_rel: str) -> str:
    return source_rel.replace("/", "__") + ".md"


def signature_filename(source_rel: str) -> str:
    return source_rel.replace("/", "__") + ".md"


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


# ──────────────────────────────────────────────────────────────────────────────
# Canonical skill loading + placeholder rendering
# ──────────────────────────────────────────────────────────────────────────────

_TOOL_BLOCK = re.compile(
    r"<!--\s*TOOL:(?P<kind>only|except|override)\s+name=\"(?P<names>[^\"]+)\"\s*-->"
    r"(?P<body>.*?)"
    r"<!--\s*TOOL:end\s*-->",
    re.DOTALL,
)


def load_canonical_skill() -> str:
    """Read the canonical SKILL.md from the installed repokb package."""
    if not CANONICAL_SKILL_PATH.exists():
        raise FileNotFoundError(
            f"Canonical SKILL.md not found at {CANONICAL_SKILL_PATH}"
        )
    return CANONICAL_SKILL_PATH.read_text(encoding="utf-8")


def apply_tool_blocks(text: str, tool: str) -> str:
    """Resolve TOOL:only/except/override blocks for a single target tool."""
    def repl(m: re.Match) -> str:
        kind = m.group("kind")
        names = {n.strip() for n in m.group("names").split(",")}
        body = m.group("body")
        if kind == "only":
            return body if tool in names else ""
        if kind == "except":
            return "" if tool in names else body
        if kind == "override":
            return body if tool in names else ""
        return ""
    return _TOOL_BLOCK.sub(repl, text)


def render_placeholders(text: str, ctx: dict) -> str:
    """Substitute {{NAME}} placeholders. Missing keys are left as-is."""
    def repl(m: re.Match) -> str:
        key = m.group(1).strip()
        if key in ctx:
            return str(ctx[key])
        return m.group(0)
    return re.sub(r"\{\{\s*([A-Z_][A-Z0-9_]*)\s*\}\}", repl, text)


def parse_skill_blocks(text: str) -> dict:
    """Lightweight introspection: report the blocks present in the canonical.

    Returned dict has keys 'tools_referenced' and 'block_count'. Used by
    tests and adapter-check; render_for_tool() is what adapters actually call.
    """
    blocks = list(_TOOL_BLOCK.finditer(text))
    tools = set()
    for m in blocks:
        for n in m.group("names").split(","):
            tools.add(n.strip())
    return {"tools_referenced": sorted(tools), "block_count": len(blocks)}


def render_for_tool(canonical: str, tool: str, ctx: dict) -> str:
    """Apply TOOL: blocks then substitute placeholders."""
    body = apply_tool_blocks(canonical, tool)
    return render_placeholders(body, ctx)


# ──────────────────────────────────────────────────────────────────────────────
# Filesystem layout
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Layout:
    root: Path

    @property
    def kb(self) -> Path:           return self.root / ".repokb"
    @property
    def manifest(self) -> Path:     return self.kb / "MANIFEST.json"
    @property
    def config(self) -> Path:       return self.kb / "config.yaml"
    @property
    def concepts(self) -> Path:     return self.kb / "concepts"
    @property
    def summaries(self) -> Path:    return self.kb / "summaries"
    @property
    def signatures(self) -> Path:   return self.kb / "signatures"
    @property
    def sources(self) -> Path:      return self.kb / "sources"
    @property
    def log(self) -> Path:          return self.kb / "log.md"
    @property
    def queue(self) -> Path:        return self.kb / ".work_queue.jsonl"
    @property
    def results(self) -> Path:      return self.kb / ".work_queue.results.jsonl"

    def ensure(self) -> None:
        for d in (self.kb, self.concepts, self.summaries,
                  self.signatures, self.sources):
            d.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# MANIFEST
# ──────────────────────────────────────────────────────────────────────────────

def empty_manifest(root: Path) -> dict:
    return {
        "version": SCHEMA_VERSION,
        "root": str(root.resolve()),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "host_tool": os.environ.get("REPOKB_HOST_TOOL", "unknown"),
        "adapters_emitted_at": None,
        "canonical_skill_sha256": None,
        "model_used": os.environ.get("REPOKB_MODEL", "unknown"),
        "config": _deepcopy_config(DEFAULT_CONFIG),
        "stats": {"sources": 0, "summaries": 0, "concepts": 0,
                  "stale_concepts": 0, "total_size_bytes": 0,
                  "signature_defer_count": 0, "signature_defer_rate": 0.0},
        "sources": [],
        "concepts": [],
        "renames_log": [],
    }


def _deepcopy_config(cfg: dict) -> dict:
    """Manual deep copy to avoid the import of `copy` for one call site."""
    out: dict = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            out[k] = dict(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def load_manifest(layout: Layout) -> dict:
    if not layout.manifest.exists():
        raise SystemExit(f"No MANIFEST at {layout.manifest}. Run `init` first.")
    return json.loads(layout.manifest.read_text())


def save_manifest(layout: Layout, m: dict) -> None:
    m["updated_at"] = now_iso()
    m["stats"] = recompute_stats(m)
    text = json.dumps(m, indent=2)
    if estimate_tokens(text) > 3000:
        print("WARNING: MANIFEST exceeds 3000-token budget. See lint PERF-01.",
              file=sys.stderr)
    layout.manifest.write_text(text)


def recompute_stats(m: dict) -> dict:
    sources = m.get("sources", [])
    sig_count = sum(1 for s in sources if s.get("signature_source") == "ast"
                    or s.get("signature_source") == "regex")
    defer_count = sum(1 for s in sources if s.get("deferred_to_source"))
    rate = (defer_count / sig_count) if sig_count else 0.0
    return {
        "sources": len(sources),
        "summaries": sum(1 for s in sources if s.get("summary")),
        "concepts": len(m.get("concepts", [])),
        "stale_concepts": sum(1 for c in m.get("concepts", []) if c.get("stale")),
        "total_size_bytes": sum(s.get("bytes", 0) for s in sources),
        "signature_defer_count": defer_count,
        "signature_defer_rate": round(rate, 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Signature skeletons
# ──────────────────────────────────────────────────────────────────────────────

def language_for_ext(ext: str) -> str | None:
    """Map a file extension (with or without dot) to its language name."""
    from repokb.adapters.extractors.registry import LANGUAGE_BY_EXT
    return LANGUAGE_BY_EXT.get(ext.lower().lstrip("."))


def format_signature_skeleton(skeleton, source_rel: str, sha256: str) -> str:
    """Render an extractors.Skeleton dataclass to a Markdown skeleton.

    Output is read by the host LLM as the ONLY input for `summarize_signature`
    jobs. Keep it dense — every symbol gets a one-line entry plus an inline
    `<<source:>>` directive so the LLM can targeted-read for unclear symbols.
    """
    lines: list[str] = []
    lines.append(f"# Signature skeleton: {source_rel}")
    lines.append("")
    lines.append(f"_Extracted by `{skeleton.extractor}` for `{skeleton.language}`._")
    lines.append(f"_Source sha256: `{sha256[:12]}...`_")
    lines.append("")

    if skeleton.module_docstring:
        lines.append("## Module docstring")
        lines.append("")
        for line in skeleton.module_docstring.splitlines():
            lines.append(f"> {line}")
        lines.append("")

    if not skeleton.symbols:
        lines.append("_No public symbols extracted. Consider falling back to "
                     "the legacy summarize job for this file._")
        return "\n".join(lines) + "\n"

    for sym in skeleton.symbols:
        lines.extend(_format_symbol(sym, source_rel, depth=0))

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**For the host LLM:** This is the COMPLETE picture of this "
                 "file's public surface. Use it to write Purpose + Notable "
                 "decisions. Do NOT read the source unless a symbol carries "
                 "`<<unclear: reason>>` — and then read ONLY that line range "
                 "via your file-read tool's offset+limit.")
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────────
# Source directive protocol
# ──────────────────────────────────────────────────────────────────────────────

_DIRECTIVE = re.compile(
    r"<<\s*source:\s*"
    r"(?P<path>[^\s:>]+)"
    r"(?:\s*:\s*(?P<start>\d+)(?:\s*-\s*(?P<end>\d+))?)?"
    r"\s*>>"
)


def parse_directives_from_text(text: str) -> list[dict]:
    """Extract every <<source:>> directive from concept Markdown.

    Returns dicts with keys: path, start (int|None), end (int|None).
    Whole-file directives produce start=None, end=None.
    Single-line forms produce start==end.
    """
    out: list[dict] = []
    for m in _DIRECTIVE.finditer(text):
        start = m.group("start")
        end = m.group("end")
        start_i = int(start) if start else None
        end_i = int(end) if end else (int(start) if start else None)
        out.append({"path": m.group("path"), "start": start_i, "end": end_i})
    return out


def parse_directives_from_concept(concept_abs_path: Path) -> list[dict]:
    if not concept_abs_path.exists():
        return []
    return parse_directives_from_text(concept_abs_path.read_text(encoding="utf-8"))


def refresh_concept_directives_mirror(layout: Layout, manifest: dict) -> None:
    """Re-parse every concept file on disk and update MANIFEST mirror.

    Called from lint (read-only assertion), from manifest-add-concept,
    from manifest-set-stale=false (post-refresh).
    """
    for c in manifest.get("concepts", []):
        concept_abs = layout.kb / c["file"]
        c["source_directives"] = parse_directives_from_concept(concept_abs)


def directive_updates_for_concept(
    layout: Layout, concept: dict, changed_sources: set[str],
    new_signatures_by_source: dict[str, object],
) -> dict[str, str]:
    """For a concept being refreshed, compute new line ranges for directives
    whose source has changed signatures.

    Returns dict like {"src/auth/jwt.py:validate_jwt": "42-71", ...}.

    Strategy: for each existing directive whose path is in changed_sources,
    find the symbol whose existing range encloses the old directive range,
    and emit the new symbol's range. Symbols are matched by name when the
    directive's range exactly matches a symbol's old range; otherwise the
    update is left for the host LLM to resolve.
    """
    updates: dict[str, str] = {}
    existing_directives = concept.get("source_directives", [])
    for d in existing_directives:
        if d["path"] not in changed_sources:
            continue
        skeleton = new_signatures_by_source.get(d["path"])
        if skeleton is None:
            continue
        # Find a symbol whose new range "is" the same symbol the directive
        # pointed at. We use name matching when feasible; fall back to
        # range-overlap when no exact name is recoverable.
        for sym in skeleton.symbols:
            # Heuristic: existing directive range overlaps the old symbol's
            # span. Since we don't have the OLD symbol range here, we fall
            # back to "symbol whose name appears in concept text near the
            # directive" — but that's expensive. For v1, emit ALL new
            # symbol ranges and let the LLM pick.
            key = f"{d['path']}:{sym.name}"
            updates[key] = f"{sym.start_line}-{sym.end_line}"
    return updates


def skeleton_fingerprint(skeleton) -> str:
    """Stable hash of a Skeleton's structural content (NOT line numbers).

    This is what powers the body-only-edit skip: when a function body changes
    but its signature, name, docstring, kind, and unclear markers don't, the
    fingerprint is identical and the LLM job is skipped.
    """
    def project(sym) -> dict:
        return {
            "name": sym.name,
            "kind": sym.kind,
            "sig": sym.signature,
            "doc": sym.docstring,
            "unclear": sorted(r.value for r in sym.unclear),
            "children": [project(c) for c in sym.children],
        }
    payload = {
        "extractor": skeleton.extractor,
        "language": skeleton.language,
        "module_doc": skeleton.module_docstring,
        "symbols": [project(s) for s in skeleton.symbols],
    }
    return sha256_text(json.dumps(payload, sort_keys=True))


def extract_and_write_signature(
    layout: Layout, source_abs: Path, source_rel: str, config: dict,
) -> tuple[object, str, str] | tuple[None, None, None]:
    """Extract a signature skeleton, write it under .repokb/signatures/.

    Returns (skeleton, sig_sha256, extractor_method_name). When the file's
    language has no enabled extractor, or the user marked the file as
    `# REPOKB: full-summary`, or the extractor produced no symbols, returns
    (None, None, None) — signaling 'fall back to the legacy summarize job'.

    sig_sha256 is a fingerprint of the skeleton's STRUCTURE (names, signatures,
    docstrings, unclear markers) — not its rendered markdown. This means a
    function-body edit that leaves the signature alone produces the same
    sig_sha256, and the script can skip the LLM job entirely.
    """
    from repokb.adapters.extractors import choose_extractor

    ext = Path(source_rel).suffix
    extractor = choose_extractor(ext, config.get("signature_extraction", {}))
    if extractor is None:
        return (None, None, None)

    skeleton = extractor.extract(source_abs, source_rel)
    if skeleton.full_summary_requested or not skeleton.symbols:
        return (None, None, None)

    sha = sha256_file(source_abs)
    sk_text = format_signature_skeleton(skeleton, source_rel, sha)
    sk_sha = skeleton_fingerprint(skeleton)

    sk_path = layout.signatures / signature_filename(source_rel)
    sk_path.parent.mkdir(parents=True, exist_ok=True)
    sk_path.write_text(sk_text, encoding="utf-8")
    return (skeleton, sk_sha, extractor.name)


def _format_symbol(sym, source_rel: str, depth: int) -> list[str]:
    prefix = "  " * depth + "- "
    kind = sym.kind
    sig = sym.signature.strip()
    directive = f"<<source: {source_rel}:{sym.start_line}-{sym.end_line}>>"
    unclear = ""
    if sym.unclear:
        reasons = ",".join(r.value for r in sym.unclear)
        unclear = f" <<unclear: {reasons}>>"
    head = f"{prefix}**{kind}** `{sym.name}{sig}` {directive}{unclear}"
    out = [head]
    if sym.docstring:
        for ln in sym.docstring.splitlines():
            out.append("  " * (depth + 1) + f"> {ln}")
    for child in sym.children:
        out.extend(_format_symbol(child, source_rel, depth + 1))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Walking
# ──────────────────────────────────────────────────────────────────────────────

def walk_sources(root: Path, config: dict) -> list[dict]:
    includes = config["include_globs"]
    excludes = config["exclude_globs"]
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if matches_any(rel, excludes):
            continue
        if includes != ["**/*"] and not matches_any(rel, includes):
            continue
        ext = p.suffix.lower()
        if ext in BINARY_DOC_EXTS and not config.get("ingest_binary_docs", True):
            continue
        type_ = ext.lstrip(".") or "text"
        out.append({
            "path": rel,
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            "type": type_,
            "language": language_for_ext(type_),
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Diffing
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Delta:
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)
    renamed: list[tuple[dict, dict]] = field(default_factory=list)  # (old, new)
    unchanged: list[dict] = field(default_factory=list)


def diff_sources(old: list[dict], new: list[dict]) -> Delta:
    old_by_path = {s["path"]: s for s in old}
    new_by_path = {s["path"]: s for s in new}
    old_by_hash = {s["sha256"]: s for s in old}

    delta = Delta()
    for path, ns in new_by_path.items():
        os_ = old_by_path.get(path)
        if os_ is None:
            # Possibly a rename
            old_match = old_by_hash.get(ns["sha256"])
            if old_match and old_match["path"] not in new_by_path:
                delta.renamed.append((old_match, ns))
            else:
                delta.added.append(ns)
        elif os_["sha256"] != ns["sha256"]:
            delta.modified.append(ns)
        else:
            delta.unchanged.append(ns)

    renamed_old_paths = {old["path"] for old, _ in delta.renamed}
    for path, os_ in old_by_path.items():
        if path not in new_by_path and path not in renamed_old_paths:
            delta.removed.append(os_)
    return delta


# ──────────────────────────────────────────────────────────────────────────────
# Work queue
# ──────────────────────────────────────────────────────────────────────────────

def queue_append(layout: Layout, job: dict) -> None:
    job.setdefault("job_id", f"j{int(time.time()*1000)}_{os.urandom(3).hex()}")
    with layout.queue.open("a") as f:
        f.write(json.dumps(job) + "\n")


def queue_clear(layout: Layout) -> None:
    layout.queue.write_text("")
    layout.results.write_text("")


# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    layout = Layout(root)

    if layout.manifest.exists() and not args.reuse_config:
        print(f"MANIFEST already exists at {layout.manifest}. "
              "Use `update` instead, or pass --reuse-config to re-init while keeping config.")
        return 1

    layout.ensure()

    if args.reuse_config and layout.manifest.exists():
        old = load_manifest(layout)
        manifest = empty_manifest(root)
        manifest["config"] = old["config"]
        manifest["created_at"] = old["created_at"]
    else:
        manifest = empty_manifest(root)

    # Walk and populate sources
    print(f"Walking {root}...", file=sys.stderr)
    sources = walk_sources(root, manifest["config"])
    print(f"Found {len(sources)} candidate sources.", file=sys.stderr)
    manifest["sources"] = [
        {**s, "summary": f"summaries/{summary_filename(s['path'])}",
         "tags": [], "signature_source": None, "sig_sha256": None}
        for s in sources
    ]

    # Extract signatures synchronously for files whose language has an
    # enabled extractor. Updates each source entry in place.
    sig_count = 0
    for s in manifest["sources"]:
        _, sig_sha, method = extract_and_write_signature(
            layout, root / s["path"], s["path"], manifest["config"],
        )
        if method is not None:
            s["signature_source"] = method
            s["sig_sha256"] = sig_sha
            s["signature_file"] = f"signatures/{signature_filename(s['path'])}"
            sig_count += 1

    save_manifest(layout, manifest)
    log_event(layout, f"init: {len(sources)} sources, {sig_count} signatures extracted")

    # Emit jobs: summarize_signature for sources with skeletons,
    # legacy summarize for the rest.
    queue_clear(layout)
    for s in manifest["sources"]:
        if s.get("sig_sha256"):
            queue_append(layout, {
                "job": "summarize_signature",
                "source_path": s["path"],
                "out_path": f".repokb/{s['summary']}",
                "signature_path": f".repokb/{s['signature_file']}",
                "sha256": s["sha256"],
                "sig_sha256": s["sig_sha256"],
                "type": s["type"],
            })
        else:
            queue_append(layout, {
                "job": "summarize",
                "source_path": s["path"],
                "out_path": f".repokb/{s['summary']}",
                "sha256": s["sha256"],
                "type": s["type"],
            })

    # Emit a single concept_init job after all summaries
    queue_append(layout, {
        "job": "concept_init",
        "summary_paths": [f".repokb/{s['summary']}" for s in manifest["sources"]],
        "manifest_path": str(layout.manifest),
    })

    print(f"\nQueued {len(manifest['sources'])} summary/signature jobs "
          f"({sig_count} signature-based) + 1 concept_init job.")
    print(f"Queue: {layout.queue}")
    print("Next: process the queue (the host LLM reads jobs, writes outputs, "
          "appends results to .work_queue.results.jsonl).")
    print("")
    print("Multi-tool support: generate instruction files for "
          "Codex/Copilot/Cursor with:")
    print("  python repokb/scripts/compile.py emit-adapters "
          "--tools claude,codex,copilot,cursor")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    layout = Layout(root)
    manifest = load_manifest(layout)

    print(f"Walking {root}...", file=sys.stderr)
    current = walk_sources(root, manifest["config"])
    delta = diff_sources(manifest["sources"], current)

    print(f"Delta: +{len(delta.added)} ~{len(delta.modified)} "
          f"-{len(delta.removed)} renamed={len(delta.renamed)} "
          f"unchanged={len(delta.unchanged)}", file=sys.stderr)

    # Apply renames first (no re-summarization).
    # Snapshot old_path/new_path before mutating: diff_sources returns the same
    # dict objects that live in manifest["sources"], so updating s["path"]
    # below would also mutate old["path"] and break the concept-update loop.
    for old, new in delta.renamed:
        old_path = old["path"]
        new_path = new["path"]
        for s in manifest["sources"]:
            if s["path"] == old_path:
                s["path"] = new_path
                s["mtime"] = new["mtime"]
                old_summary = layout.kb / s["summary"]
                new_summary_rel = f"summaries/{summary_filename(new_path)}"
                new_summary = layout.kb / new_summary_rel
                if old_summary.exists():
                    old_summary.rename(new_summary)
                s["summary"] = new_summary_rel
                break
        for c in manifest["concepts"]:
            c["touches_sources"] = [
                new_path if p == old_path else p
                for p in c["touches_sources"]
            ]
        manifest["renames_log"].append(
            {"from": old_path, "to": new_path, "at": now_iso()}
        )

    # Apply deletions
    removed_paths = {s["path"] for s in delta.removed}
    if removed_paths:
        for s in delta.removed:
            sf = layout.kb / s["summary"]
            if sf.exists():
                sf.unlink()
        manifest["sources"] = [s for s in manifest["sources"]
                               if s["path"] not in removed_paths]
        # Cascade staleness
        for c in manifest["concepts"]:
            if any(p in removed_paths for p in c["touches_sources"]):
                c["stale"] = True
                c["touches_sources"] = [p for p in c["touches_sources"]
                                        if p not in removed_paths]

    # Apply additions
    for s in delta.added:
        manifest["sources"].append({
            **s,
            "summary": f"summaries/{summary_filename(s['path'])}",
            "tags": [],
        })

    # Apply modifications (update hash/mtime, keep summary path)
    modified_paths = {s["path"] for s in delta.modified}
    for s in manifest["sources"]:
        if s["path"] in modified_paths:
            for ns in delta.modified:
                if ns["path"] == s["path"]:
                    s["sha256"] = ns["sha256"]
                    s["bytes"] = ns["bytes"]
                    s["mtime"] = ns["mtime"]
                    break

    # Re-extract signatures for added + modified files. Track which
    # modified files had ZERO signature change (body-only edit) — those skip
    # the LLM entirely. Also collect the new Skeletons so the
    # concept_refresh jobs can carry directive_updates.
    body_only_unchanged: set[str] = set()
    new_skeletons_by_source: dict[str, object] = {}
    for s in manifest["sources"]:
        if s["path"] not in (modified_paths | {a["path"] for a in delta.added}):
            continue
        old_sig = s.get("sig_sha256")
        skeleton, new_sig, method = extract_and_write_signature(
            layout, root / s["path"], s["path"], manifest["config"],
        )
        if method is not None:
            s["signature_source"] = method
            s["sig_sha256"] = new_sig
            s["signature_file"] = f"signatures/{signature_filename(s['path'])}"
            new_skeletons_by_source[s["path"]] = skeleton
            if old_sig is not None and old_sig == new_sig \
                    and s["path"] in modified_paths:
                body_only_unchanged.add(s["path"])
        else:
            # No extractor — clear any stale signature reference.
            s["signature_source"] = None
            s["sig_sha256"] = None
            s.pop("signature_file", None)

    # Cascade staleness for added + modified, but EXCLUDE files whose
    # signature didn't change (their summary is still accurate).
    real_changes = ({s["path"] for s in delta.added}
                    | (modified_paths - body_only_unchanged))
    for c in manifest["concepts"]:
        if any(p in real_changes for p in c["touches_sources"]):
            c["stale"] = True

    save_manifest(layout, manifest)
    log_event(
        layout,
        f"update: +{len(delta.added)} ~{len(delta.modified)} "
        f"-{len(delta.removed)} renamed={len(delta.renamed)} "
        f"body-only-skipped={len(body_only_unchanged)}"
    )

    # Emit summary / summarize_signature jobs for added + (modified \ body-only).
    queue_clear(layout)
    queueable = list(delta.added) + [
        ns for ns in delta.modified if ns["path"] not in body_only_unchanged
    ]
    for ns in queueable:
        # Find the up-to-date source entry in MANIFEST (which now has the
        # latest signature data).
        s = next(x for x in manifest["sources"] if x["path"] == ns["path"])
        out_rel = f"summaries/{summary_filename(s['path'])}"
        if s.get("sig_sha256"):
            queue_append(layout, {
                "job": "summarize_signature",
                "source_path": s["path"],
                "out_path": f".repokb/{out_rel}",
                "signature_path": f".repokb/{s['signature_file']}",
                "sha256": s["sha256"],
                "sig_sha256": s["sig_sha256"],
                "type": s["type"],
            })
        else:
            queue_append(layout, {
                "job": "summarize",
                "source_path": s["path"],
                "out_path": f".repokb/{out_rel}",
                "sha256": s["sha256"],
                "type": s["type"],
            })

    # Emit concept refresh jobs for stale concepts
    stale_concepts = [c for c in manifest["concepts"] if c.get("stale")]
    for c in stale_concepts:
        summaries_to_reread = [
            f".repokb/summaries/{summary_filename(p)}"
            for p in c["touches_sources"]
            if p in real_changes
        ]
        directive_updates = directive_updates_for_concept(
            layout, c, real_changes, new_skeletons_by_source,
        )
        job = {
            "job": "concept_refresh",
            "concept_id": c["id"],
            "current_path": f".repokb/{c['file']}",
            "summaries_to_reread": summaries_to_reread,
            "stale_reason": f"{len(summaries_to_reread)} touched source(s) changed",
        }
        if directive_updates:
            job["directive_updates"] = directive_updates
        queue_append(layout, job)

    # Heuristic: suggest full re-compile if too many concepts went stale
    if manifest["concepts"]:
        stale_ratio = len(stale_concepts) / len(manifest["concepts"])
        if stale_ratio > 0.6:
            print(f"\nNOTE: {stale_ratio:.0%} of concepts went stale. "
                  "Consider `rm -rf .repokb/concepts .repokb/summaries && "
                  "compile.py init --reuse-config` for a cleaner re-cluster.",
                  file=sys.stderr)

    queued = len(queueable)
    print(f"\nQueued {queued} summary jobs ({len(body_only_unchanged)} "
          f"body-only edits skipped) + {len(stale_concepts)} concept refresh jobs.")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root).resolve())
    manifest = load_manifest(layout)
    issues = []

    # STRUCT-01
    for c in manifest["concepts"]:
        if c.get("stale"):
            issues.append(("STRUCT-01", "error",
                           f"stale concept: {c['id']}"))

    # STRUCT-02
    summary_paths_in_manifest = {s["summary"] for s in manifest["sources"]}
    referenced_sources = set()
    for c in manifest["concepts"]:
        referenced_sources.update(c["touches_sources"])
    marginal = set(manifest["config"].get("marginal_sources", []))
    for s in manifest["sources"]:
        if s["path"] not in referenced_sources and s["path"] not in marginal:
            issues.append(("STRUCT-06", "info",
                           f"unreferenced source: {s['path']}"))

    # STRUCT-04
    for c in manifest["concepts"]:
        if c.get("tokens_est", 0) > manifest["config"]["max_concept_tokens"]:
            issues.append(("STRUCT-04", "error",
                           f"concept exceeds budget: {c['id']} "
                           f"({c['tokens_est']} tokens)"))

    # STRUCT-05
    for c in manifest["concepts"]:
        if len(c["touches_sources"]) == 1:
            issues.append(("STRUCT-05", "warning",
                           f"single-source concept: {c['id']}"))

    # PERF-01
    manifest_size = estimate_tokens(json.dumps(manifest))
    if manifest_size > 0.8 * 3000:
        issues.append(("PERF-01", "warning",
                       f"MANIFEST size {manifest_size} tokens "
                       f"({manifest_size/3000:.0%} of budget)"))

    # PERF-02
    if len(manifest["concepts"]) > manifest["config"]["max_concepts"]:
        issues.append(("PERF-02", "error",
                       f"{len(manifest['concepts'])} concepts > "
                       f"{manifest['config']['max_concepts']} cap. "
                       "See references/scaling.md"))

    # PERF-03
    for c in manifest["concepts"]:
        if len(c["touches_sources"]) > 20:
            issues.append(("PERF-03", "warning",
                           f"concept fanout: {c['id']} "
                           f"touches {len(c['touches_sources'])} sources"))

    # KNOW-01
    for c in manifest["concepts"]:
        for gap in c.get("gaps", []):
            issues.append(("KNOW-01", "info",
                           f"gap in {c['id']}: {gap.get('description', gap)}"))

    # STRUCT-07 — adapter drift (rendered emitted files out of sync with
    # what the canonical SKILL.md would currently produce).
    try:
        from repokb.adapters import ADAPTERS
        from repokb.adapters.base import ParsedCanonical
        canonical = load_canonical_skill()
        canonical_sha = sha256_text(canonical)
        parsed = ParsedCanonical(common=canonical, blocks=[], raw=canonical)
        for name, adapter in ADAPTERS.items():
            out_path = adapter.output_path(layout.root)
            if not out_path.exists():
                continue
            actual = out_path.read_text(encoding="utf-8")
            stamp = _read_stamp(actual)
            if stamp is None:
                issues.append((
                    "STRUCT-07", "warning",
                    f"adapter {name}: emitted file has no RepoKB stamp "
                    f"({out_path})"
                ))
                continue
            if stamp["conv"] != adapter.convention_version:
                issues.append((
                    "STRUCT-07", "warning",
                    f"adapter {name}: stamped CONVENTION_VERSION "
                    f"{stamp['conv']} != current {adapter.convention_version}"
                ))
            # Re-render and compare. We must replicate the merge logic from
            # emit-adapters to compare apples to apples.
            ctx = adapter.make_context(canonical_sha)
            body = adapter.transform(parsed, ctx)
            if adapter.critical_banner and not adapter.incorporates_banner:
                body = adapter.critical_banner + "\n\n" + body
            body += adapter.trailing_stamp(ctx)
            if adapter.merge_mode == "sentinel":
                expected = _apply_sentinel(actual, body) if "<!-- repokb:start" in actual else body
            else:
                expected = body
            if actual.strip() != expected.strip():
                issues.append((
                    "STRUCT-07", "error",
                    f"adapter {name}: emitted file drifted from canonical; "
                    "re-run `emit-adapters --diff-only` to see, then "
                    "`emit-adapters` to fix"
                ))
    except FileNotFoundError:
        pass   # No canonical SKILL.md present — skip the rule.

    # STRUCT-08 — source directives must reference a source in touches_sources
    # AND must point to a valid line range
    source_lines: dict[str, int] = {}
    for c in manifest["concepts"]:
        touches = set(c.get("touches_sources", []))
        for d in c.get("source_directives", []):
            if d["path"] not in touches:
                issues.append((
                    "STRUCT-08", "error",
                    f"orphan directive in {c['id']}: {d['path']} not in "
                    f"touches_sources"
                ))
                continue
            if d["end"] is None:
                continue   # whole-file form, no range to validate
            source_abs = layout.root / d["path"]
            if not source_abs.exists():
                issues.append((
                    "STRUCT-08", "warning",
                    f"directive in {c['id']}: {d['path']} not on disk"
                ))
                continue
            if d["path"] not in source_lines:
                try:
                    source_lines[d["path"]] = sum(
                        1 for _ in source_abs.open("rb")
                    )
                except OSError:
                    source_lines[d["path"]] = 0
            n = source_lines[d["path"]]
            if d["start"] > n or d["end"] > n:
                issues.append((
                    "STRUCT-08", "error",
                    f"directive in {c['id']}: {d['path']}:{d['start']}-"
                    f"{d['end']} exceeds file length {n}"
                ))

    # STRUCT-09 — concept page is code-block-heavy (>5 fenced blocks
    # suggests the concept is a code copy, not a synthesis)
    for c in manifest["concepts"]:
        concept_abs = layout.kb / c["file"]
        if not concept_abs.exists():
            continue
        text = concept_abs.read_text(encoding="utf-8", errors="ignore")
        fences = text.count("\n```")
        # Each fenced block has an opening and closing fence; divide by 2.
        n_blocks = fences // 2
        if n_blocks > 5:
            issues.append((
                "STRUCT-09", "warning",
                f"code-block-heavy concept: {c['id']} has {n_blocks} fenced "
                "blocks; prefer prose-with-citation via <<source:>>"
            ))

    # PERF-04 — signature_defer_rate too high (AST extraction not paying off)
    defer_rate = manifest.get("stats", {}).get("signature_defer_rate", 0.0)
    if defer_rate > 0.30:
        issues.append((
            "PERF-04", "warning",
            f"signature defer rate is {defer_rate:.0%} (>30%); consider "
            "setting signature_extraction.<language>: false for the "
            "languages where the LLM keeps deferring to source"
        ))

    by_rule = {}
    for rule, sev, msg in issues:
        by_rule.setdefault((rule, sev), []).append(msg)

    if not issues:
        print("KB is healthy. No lint issues.")
        return 0

    severity_order = {"error": 0, "warning": 1, "info": 2}
    for (rule, sev), msgs in sorted(by_rule.items(),
                                    key=lambda kv: (severity_order[kv[0][1]], kv[0][0])):
        print(f"\n## {rule} ({sev}) — {len(msgs)} issue(s)")
        for m in msgs:
            print(f"  - {m}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root).resolve())
    manifest = load_manifest(layout)
    print(f"Root: {manifest['root']}")
    print(f"Updated: {manifest['updated_at']}")
    print(f"Host tool: {manifest.get('host_tool', 'unknown')}")
    print(f"Model: {manifest['model_used']}")
    print(f"Stats: {manifest['stats']}")
    print(f"Manifest size: ~{estimate_tokens(json.dumps(manifest))} tokens")
    if manifest.get("adapters_emitted_at"):
        print(f"Adapters last emitted: {manifest['adapters_emitted_at']}")
    if layout.log.exists():
        tail = layout.log.read_text().splitlines()[-10:]
        print("\nRecent log:")
        for line in tail:
            print(f"  {line}")
    if args.directive_stats:
        _print_directive_stats(layout)
    return 0


def _print_directive_stats(layout: Layout) -> None:
    """Parse audit log entries from .repokb/log.md to surface directive use."""
    if not layout.log.exists():
        print("\nDirective stats: no log file.")
        return
    lines = layout.log.read_text(encoding="utf-8", errors="ignore").splitlines()
    ranged = 0
    whole = 0
    by_path: dict[str, int] = {}
    rx_ranged = re.compile(r"resolve\s+(?P<p>\S+):(\d+)-(\d+)")
    rx_whole = re.compile(r"resolve\s+(?P<p>\S+)\s+\(whole file")
    for line in lines:
        m = rx_ranged.search(line)
        if m:
            ranged += 1
            by_path[m.group("p")] = by_path.get(m.group("p"), 0) + 1
            continue
        m = rx_whole.search(line)
        if m:
            whole += 1
            by_path[m.group("p")] = by_path.get(m.group("p"), 0) + 1
    total = ranged + whole
    print("\nDirective stats:")
    if total == 0:
        print("  No resolution log entries (audit_directives may be off).")
        return
    print(f"  total resolutions: {total}")
    print(f"  ranged loads:      {ranged} ({ranged * 100 // total}%)")
    print(f"  whole-file loads:  {whole} ({whole * 100 // total}%)")
    if whole and ranged * 4 < whole:
        print("  WARNING: whole-file loads dominate. Either the LLM is "
              "ignoring the directive protocol, or concepts need more "
              "granular <<source:>> directives.")
    print("  top sources:")
    for path, count in sorted(by_path.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {count:4}  {path}")


def cmd_manifest_add_concept(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root).resolve())
    manifest = load_manifest(layout)
    if any(c["id"] == args.id for c in manifest["concepts"]):
        print(f"Concept {args.id} already exists.", file=sys.stderr)
        return 1
    concept_file = (layout.kb / args.file).resolve()
    try:
        rel_file = concept_file.relative_to(layout.kb).as_posix()
    except ValueError:
        rel_file = args.file
    tokens_est = 0
    directives: list[dict] = []
    if concept_file.exists():
        text = concept_file.read_text()
        tokens_est = estimate_tokens(text)
        directives = parse_directives_from_text(text)
    manifest["concepts"].append({
        "id": args.id,
        "file": rel_file,
        "topics": [t.strip() for t in args.topics.split(",")],
        "touches_sources": [t.strip() for t in args.touches.split(",")],
        "source_directives": directives,
        "related_concepts": [],
        "tokens_est": tokens_est,
        "stale": False,
        "last_synthesized": now_iso(),
        "gaps": [],
    })
    save_manifest(layout, manifest)
    log_event(layout, f"add-concept: {args.id}")
    print(f"Added concept {args.id} ({tokens_est} tokens est., "
          f"{len(directives)} directive(s))")
    return 0


def cmd_manifest_set_stale(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root).resolve())
    manifest = load_manifest(layout)
    for c in manifest["concepts"]:
        if c["id"] == args.concept:
            c["stale"] = args.stale.lower() == "true"
            if not c["stale"]:
                c["last_synthesized"] = now_iso()
                cf = layout.kb / c["file"]
                if cf.exists():
                    text = cf.read_text()
                    c["tokens_est"] = estimate_tokens(text)
                    c["source_directives"] = parse_directives_from_text(text)
            save_manifest(layout, manifest)
            log_event(layout, f"set-stale {args.concept}={c['stale']}")
            return 0
    print(f"Concept {args.concept} not found.", file=sys.stderr)
    return 1


def cmd_manifest_remove_source(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root).resolve())
    manifest = load_manifest(layout)
    before = len(manifest["sources"])
    manifest["sources"] = [s for s in manifest["sources"] if s["path"] != args.path]
    if len(manifest["sources"]) == before:
        print(f"Source {args.path} not in manifest.", file=sys.stderr)
        return 1
    for c in manifest["concepts"]:
        if args.path in c["touches_sources"]:
            c["touches_sources"].remove(args.path)
            c["stale"] = True
    save_manifest(layout, manifest)
    log_event(layout, f"remove-source: {args.path}")
    return 0


def cmd_prune_orphan(args: argparse.Namespace) -> int:
    layout = Layout(Path(args.root).resolve())
    p = layout.kb / args.path
    if not p.exists():
        print(f"{p} does not exist.", file=sys.stderr)
        return 1
    p.unlink()
    log_event(layout, f"prune-orphan: {args.path}")
    print(f"Removed {p}.")
    return 0


def log_event(layout: Layout, msg: str) -> None:
    layout.log.parent.mkdir(parents=True, exist_ok=True)
    with layout.log.open("a") as f:
        f.write(f"- {now_iso()}: {msg}\n")


# ──────────────────────────────────────────────────────────────────────────────
# emit-adapters
# ──────────────────────────────────────────────────────────────────────────────

_STAMP_RE = re.compile(
    r"<!--\s*generated by repokb emit-adapters@(?P<skill>\S+)\s+"
    r"from SKILL\.md@(?P<sha>[0-9a-f]+)\s*\n"
    r"\s*adapter:\s*(?P<adapter>\w+)\s+CONVENTION_VERSION=(?P<conv>\S+);"
    r"\s*do not edit\s*-->",
    re.DOTALL,
)


def _read_stamp(text: str) -> dict | None:
    m = _STAMP_RE.search(text)
    if not m:
        return None
    return {"skill": m.group("skill"), "sha": m.group("sha"),
            "adapter": m.group("adapter"), "conv": m.group("conv")}


def _apply_sentinel(existing: str, generated_body: str) -> str:
    """Insert generated_body between repokb:start/end sentinels.

    If sentinels exist: replace just the inner content.
    If they don't:     append a new sentinel block at the end.
    """
    from repokb.adapters.base import SENTINEL_START, SENTINEL_END
    pattern = re.compile(
        re.escape(SENTINEL_START) + r".*?" + re.escape(SENTINEL_END),
        re.DOTALL,
    )
    block = f"{SENTINEL_START}\n{generated_body.strip()}\n{SENTINEL_END}"
    if pattern.search(existing):
        return pattern.sub(block, existing)
    sep = "\n\n" if existing.strip() else ""
    return f"{existing.rstrip()}{sep}{block}\n"


def _plan_writes(adapters, parsed, canonical_sha, repo_root: Path, mode: str | None):
    """Return list of (adapter, path, new_text, old_text_or_None, action)."""
    plan = []
    for adapter in adapters:
        out_path = adapter.output_path(repo_root)
        ctx = adapter.make_context(canonical_sha)
        body = adapter.transform(parsed, ctx)
        if adapter.critical_banner and not adapter.incorporates_banner:
            body = adapter.critical_banner + "\n\n" + body
        body += adapter.trailing_stamp(ctx)

        effective_mode = mode or adapter.merge_mode
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        if effective_mode == "sentinel" and existing is not None:
            new_text = _apply_sentinel(existing, body)
        elif effective_mode == "sentinel" and existing is None:
            from repokb.adapters.base import SENTINEL_START, SENTINEL_END
            new_text = f"{SENTINEL_START}\n{body.strip()}\n{SENTINEL_END}\n"
        else:  # replace
            new_text = body

        if existing is None:
            action = "create"
        elif existing == new_text:
            action = "unchanged"
        else:
            action = "modify"
        plan.append((adapter, out_path, new_text, existing, action))
    return plan


def _print_preflight(plan, repo_root: Path) -> None:
    print(f"emit-adapters will touch the following paths (repo root: {repo_root}):")
    for adapter, path, new_text, existing, action in plan:
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            rel = path
        size = len(new_text)
        if action == "create":
            print(f"  [create]   {rel}  ({size} chars)")
        elif action == "unchanged":
            print(f"  [skip]     {rel}  (no change)")
        else:
            old_lines = (existing or "").splitlines()
            new_lines = new_text.splitlines()
            delta_add = max(0, len(new_lines) - len(old_lines))
            delta_del = max(0, len(old_lines) - len(new_lines))
            print(f"  [modify]   {rel}  (+{delta_add} / -{delta_del} lines)")


def _print_diff(plan, repo_root: Path) -> int:
    """Print unified diff; return 1 if any drift else 0."""
    import difflib
    drift = 0
    for adapter, path, new_text, existing, action in plan:
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            rel = str(path)
        if action == "unchanged":
            continue
        drift = 1
        old_lines = (existing or "").splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{rel}", tofile=f"b/{rel}",
        )
        for line in diff:
            print(line, end="" if line.endswith("\n") else "\n")
    return drift


def cmd_emit_adapters(args: argparse.Namespace) -> int:
    from repokb.adapters import ADAPTERS

    repo_root = Path(args.root).resolve()
    requested = args.tools.split(",") if args.tools else list(ADAPTERS)
    if requested == ["all"]:
        requested = list(ADAPTERS)
    requested = [t.strip() for t in requested if t.strip()]
    unknown = [t for t in requested if t not in ADAPTERS]
    if unknown:
        print(f"ERROR: unknown adapter(s): {unknown}. "
              f"Known: {sorted(ADAPTERS)}", file=sys.stderr)
        return 2

    canonical = load_canonical_skill()
    canonical_sha = sha256_text(canonical)
    from repokb.adapters.base import ParsedCanonical
    parsed = ParsedCanonical(common=canonical, blocks=[], raw=canonical)

    selected = [ADAPTERS[name] for name in requested]
    plan = _plan_writes(selected, parsed, canonical_sha, repo_root, args.mode)

    if args.diff_only:
        return _print_diff(plan, repo_root)

    _print_preflight(plan, repo_root)
    if args.dry_run:
        print("\n--dry-run: no files written.")
        return 0

    if not args.yes and sys.stdin.isatty():
        try:
            resp = input("\nProceed with these writes? [y/N] ")
        except EOFError:
            resp = ""
        if resp.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return 1
    elif not args.yes:
        print("ERROR: not a TTY and --yes was not passed; refusing to write.",
              file=sys.stderr)
        return 2

    written = 0
    skipped = []
    for adapter, path, new_text, existing, action in plan:
        if action == "unchanged":
            continue
        # Drift guard: existing file has no RepoKB stamp AND no sentinel
        if (existing is not None and action == "modify"
                and adapter.merge_mode == "replace"
                and _read_stamp(existing) is None
                and not args.force):
            skipped.append((path, "no RepoKB stamp; pass --force to overwrite"))
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_text, encoding="utf-8")
            written += 1
        except OSError as e:
            print(f"WARNING: failed to write {path}: {e}", file=sys.stderr)

    # Update MANIFEST stamp if it exists.
    layout = Layout(repo_root)
    if layout.manifest.exists():
        try:
            m = load_manifest(layout)
            m["adapters_emitted_at"] = now_iso()
            m["canonical_skill_sha256"] = canonical_sha
            save_manifest(layout, m)
        except SystemExit:
            pass   # No manifest? Fine, emit-adapters works without one.

    print(f"\nWrote {written} file(s).")
    for path, reason in skipped:
        print(f"  skipped {path}: {reason}", file=sys.stderr)
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    """Upgrade a v1 .repokb/ in place to v2 schema.

    Fills new top-level fields with sensible defaults and tags each source
    as needing signature extraction on the next update. No mass re-summary;
    the efficiency wins kick in lazily.
    """
    layout = Layout(Path(args.root).resolve())
    if not layout.manifest.exists():
        print(f"No MANIFEST at {layout.manifest}. Nothing to migrate.",
              file=sys.stderr)
        return 1

    manifest = json.loads(layout.manifest.read_text())
    current_version = manifest.get("version", 0)
    target_version = args.to_version

    if current_version == target_version:
        print(f"MANIFEST is already at version {target_version}. "
              "Nothing to do.")
        return 0
    if current_version > target_version:
        print(f"MANIFEST version {current_version} is newer than target "
              f"{target_version}. Refusing to downgrade.", file=sys.stderr)
        return 2
    if current_version != 1 or target_version != 2:
        print(f"Only v1->v2 migration is implemented "
              f"(got {current_version}->{target_version}).", file=sys.stderr)
        return 2

    # Top-level v2 fields
    manifest.setdefault("host_tool", "claude")
    manifest.setdefault("adapters_emitted_at", None)
    manifest.setdefault("canonical_skill_sha256", None)

    # Config additions
    cfg = manifest.setdefault("config", {})
    cfg.setdefault("signature_extraction", DEFAULT_CONFIG["signature_extraction"])
    cfg.setdefault("audit_directives", False)

    # Stats additions
    stats = manifest.setdefault("stats", {})
    stats.setdefault("signature_defer_count", 0)
    stats.setdefault("signature_defer_rate", 0.0)

    # Source additions — defaults flag "no signature yet, populate lazily".
    for s in manifest.get("sources", []):
        s.setdefault("signature_source", None)
        s.setdefault("sig_sha256", None)

    # Concept additions — empty directives list (populated on next refresh).
    for c in manifest.get("concepts", []):
        c.setdefault("source_directives", [])

    manifest["version"] = target_version
    layout.ensure()
    layout.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log_event(layout, f"migrate v1->v{target_version}")

    print(f"Migrated MANIFEST to version {target_version}.")
    print("Next steps:")
    print("  1. Run `emit-adapters` to generate per-tool instruction files.")
    print("  2. Existing summaries and concepts are preserved.")
    print("  3. Signatures and directives will populate lazily as files change.")
    return 0


def cmd_extract_signatures(args: argparse.Namespace) -> int:
    """Extract (or re-extract) signature skeletons for selected sources.

    Standalone tool for debugging or for users who change signature_extraction
    config and want the skeletons refreshed without going through update.
    """
    root = Path(args.root).resolve()
    layout = Layout(root)
    manifest = load_manifest(layout)
    config = manifest["config"]

    if args.paths:
        wanted = {p.strip() for p in args.paths.split(",") if p.strip()}
        targets = [s for s in manifest["sources"] if s["path"] in wanted]
        missing = wanted - {s["path"] for s in targets}
        for m in missing:
            print(f"WARNING: {m} not in MANIFEST", file=sys.stderr)
    else:
        targets = list(manifest["sources"])

    written = 0
    skipped = 0
    for s in targets:
        _, sig_sha, method = extract_and_write_signature(
            layout, root / s["path"], s["path"], config,
        )
        if method is None:
            skipped += 1
            continue
        s["signature_source"] = method
        s["sig_sha256"] = sig_sha
        s["signature_file"] = f"signatures/{signature_filename(s['path'])}"
        written += 1

    save_manifest(layout, manifest)
    print(f"Extracted signatures for {written}/{len(targets)} sources "
          f"({skipped} skipped: no extractor or full-summary opt-out).")
    return 0


def cmd_adapter_check(args: argparse.Namespace) -> int:
    """Validate that each emitted file's stamped CONVENTION_VERSION matches
    the adapter class's current convention_version."""
    from repokb.adapters import ADAPTERS

    repo_root = Path(args.root).resolve()
    issues = 0
    for name, adapter in ADAPTERS.items():
        out_path = adapter.output_path(repo_root)
        if not out_path.exists():
            print(f"[skip]    {name}: {out_path} not present")
            continue
        text = out_path.read_text(encoding="utf-8")
        stamp = _read_stamp(text)
        if stamp is None:
            print(f"[ERROR]   {name}: {out_path} missing RepoKB stamp")
            issues += 1
            continue
        if stamp["conv"] != adapter.convention_version:
            print(f"[WARN]    {name}: stamped {stamp['conv']} != "
                  f"current {adapter.convention_version}")
            issues += 1
            continue
        print(f"[ok]      {name}: {stamp['conv']}")
    return 1 if issues else 0


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="compile.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init")
    sp.add_argument("--root", default=".")
    sp.add_argument("--config-from-interview", action="store_true")
    sp.add_argument("--reuse-config", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("update")
    sp.add_argument("--root", default=".")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("lint")
    sp.add_argument("--root", default=".")
    sp.set_defaults(func=cmd_lint)

    sp = sub.add_parser("inspect")
    sp.add_argument("--root", default=".")
    sp.add_argument("--directive-stats", action="store_true",
                    help="Surface directive resolution stats from log.md")
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser("manifest-add-concept")
    sp.add_argument("--root", default=".")
    sp.add_argument("--id", required=True)
    sp.add_argument("--topics", required=True, help="comma-separated")
    sp.add_argument("--touches", required=True, help="comma-separated paths")
    sp.add_argument("--file", required=True, help="path under .repokb/")
    sp.set_defaults(func=cmd_manifest_add_concept)

    sp = sub.add_parser("manifest-set-stale")
    sp.add_argument("--root", default=".")
    sp.add_argument("--concept", required=True)
    sp.add_argument("--stale", required=True, choices=["true", "false"])
    sp.set_defaults(func=cmd_manifest_set_stale)

    sp = sub.add_parser("manifest-remove-source")
    sp.add_argument("--root", default=".")
    sp.add_argument("--path", required=True)
    sp.set_defaults(func=cmd_manifest_remove_source)

    sp = sub.add_parser("prune-orphan-summary")
    sp.add_argument("--root", default=".")
    sp.add_argument("--path", required=True, help="path under .repokb/")
    sp.set_defaults(func=cmd_prune_orphan)

    sp = sub.add_parser("emit-adapters",
                        help="Generate per-tool instruction files from canonical SKILL.md")
    sp.add_argument("--root", default=".")
    sp.add_argument("--tools", default="",
                    help="comma-separated adapter names, or 'all' (default: all)")
    sp.add_argument("--mode", choices=["merge", "replace"], default=None,
                    help="Override per-adapter default merge mode")
    sp.add_argument("--dry-run", action="store_true",
                    help="Print plan but write nothing")
    sp.add_argument("--diff-only", action="store_true",
                    help="Print unified diff and exit (1=drift, 0=clean)")
    sp.add_argument("--yes", action="store_true",
                    help="Skip the pre-flight confirmation prompt")
    sp.add_argument("--force", action="store_true",
                    help="Overwrite even if target file has no RepoKB stamp")
    sp.set_defaults(func=cmd_emit_adapters)

    sp = sub.add_parser("adapter-check",
                        help="Validate adapter CONVENTION_VERSION stamps")
    sp.add_argument("--root", default=".")
    sp.set_defaults(func=cmd_adapter_check)

    sp = sub.add_parser("extract-signatures",
                        help="Re-extract AST/regex skeletons for selected sources")
    sp.add_argument("--root", default=".")
    sp.add_argument("--paths", default="",
                    help="comma-separated source paths (default: all)")
    sp.set_defaults(func=cmd_extract_signatures)

    sp = sub.add_parser("migrate",
                        help="Upgrade an existing .repokb/ to a new schema version")
    sp.add_argument("--root", default=".")
    sp.add_argument("--to-version", type=int, default=2)
    sp.set_defaults(func=cmd_migrate)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
