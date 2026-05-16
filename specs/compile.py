#!/usr/bin/env python3
"""
compile.py — RepoKB orchestrator.

Handles deterministic work: walking, hashing, MANIFEST maintenance, work queue.
Calls back to Claude (the LLM running this skill) for summarization and synthesis
via a JSONL work queue protocol.

Usage:
    compile.py init [--root PATH] [--config-from-interview | --reuse-config]
    compile.py update [--root PATH]
    compile.py lint [--root PATH]
    compile.py inspect [--root PATH]
    compile.py manifest-add-concept --id ID --topics "a,b,c" --touches "p1,p2" --file PATH
    compile.py manifest-set-stale --concept ID --stale BOOL
    compile.py manifest-remove-source --path PATH
    compile.py prune-orphan-summary --path PATH

Design note:
    This script never calls an LLM. It writes work-queue jobs to
    .repokb/.work_queue.jsonl and reads results from
    .repokb/.work_queue.results.jsonl. The skill's caller (Claude) is
    responsible for processing the queue between script invocations.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1
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
}
BINARY_DOC_EXTS = {".pdf", ".docx", ".pptx", ".xlsx"}


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


def summary_filename(source_rel: str) -> str:
    return source_rel.replace("/", "__") + ".md"


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


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
    def sources(self) -> Path:      return self.kb / "sources"
    @property
    def log(self) -> Path:          return self.kb / "log.md"
    @property
    def queue(self) -> Path:        return self.kb / ".work_queue.jsonl"
    @property
    def results(self) -> Path:      return self.kb / ".work_queue.results.jsonl"

    def ensure(self) -> None:
        for d in (self.kb, self.concepts, self.summaries, self.sources):
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
        "model_used": os.environ.get("REPOKB_MODEL", "unknown"),
        "config": DEFAULT_CONFIG.copy(),
        "stats": {"sources": 0, "summaries": 0, "concepts": 0,
                  "stale_concepts": 0, "total_size_bytes": 0},
        "sources": [],
        "concepts": [],
        "renames_log": [],
    }


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
    return {
        "sources": len(m["sources"]),
        "summaries": sum(1 for s in m["sources"] if s.get("summary")),
        "concepts": len(m["concepts"]),
        "stale_concepts": sum(1 for c in m["concepts"] if c.get("stale")),
        "total_size_bytes": sum(s.get("bytes", 0) for s in m["sources"]),
    }


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
        out.append({
            "path": rel,
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            "type": ext.lstrip(".") or "text",
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
        {**s, "summary": f"summaries/{summary_filename(s['path'])}", "tags": []}
        for s in sources
    ]

    save_manifest(layout, manifest)
    log_event(layout, f"init: {len(sources)} sources discovered")

    # Emit summary jobs for everything
    queue_clear(layout)
    for s in manifest["sources"]:
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

    print(f"\nQueued {len(manifest['sources'])} summary jobs + 1 concept_init job.")
    print(f"Queue: {layout.queue}")
    print("Next: process the queue (Claude reads jobs, writes outputs, "
          "appends results to .work_queue.results.jsonl).")
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

    # Apply renames first (no re-summarization)
    for old, new in delta.renamed:
        for s in manifest["sources"]:
            if s["path"] == old["path"]:
                s["path"] = new["path"]
                s["mtime"] = new["mtime"]
                old_summary = layout.kb / s["summary"]
                new_summary_rel = f"summaries/{summary_filename(new['path'])}"
                new_summary = layout.kb / new_summary_rel
                if old_summary.exists():
                    old_summary.rename(new_summary)
                s["summary"] = new_summary_rel
                break
        for c in manifest["concepts"]:
            c["touches_sources"] = [
                new["path"] if p == old["path"] else p
                for p in c["touches_sources"]
            ]
        manifest["renames_log"].append(
            {"from": old["path"], "to": new["path"], "at": now_iso()}
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

    # Cascade staleness for added + modified
    changed_paths = {s["path"] for s in delta.added} | modified_paths
    for c in manifest["concepts"]:
        if any(p in changed_paths for p in c["touches_sources"]):
            c["stale"] = True

    save_manifest(layout, manifest)
    log_event(layout, f"update: +{len(delta.added)} ~{len(delta.modified)} "
                      f"-{len(delta.removed)} renamed={len(delta.renamed)}")

    # Emit summary jobs for added + modified
    queue_clear(layout)
    for s in delta.added + delta.modified:
        out_rel = f"summaries/{summary_filename(s['path'])}"
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
            if p in changed_paths
        ]
        queue_append(layout, {
            "job": "concept_refresh",
            "concept_id": c["id"],
            "current_path": f".repokb/{c['file']}",
            "summaries_to_reread": summaries_to_reread,
            "stale_reason": f"{len(summaries_to_reread)} touched source(s) changed",
        })

    # Heuristic: suggest full re-compile if too many concepts went stale
    if manifest["concepts"]:
        stale_ratio = len(stale_concepts) / len(manifest["concepts"])
        if stale_ratio > 0.6:
            print(f"\nNOTE: {stale_ratio:.0%} of concepts went stale. "
                  "Consider `rm -rf .repokb/concepts .repokb/summaries && "
                  "compile.py init --reuse-config` for a cleaner re-cluster.",
                  file=sys.stderr)

    print(f"\nQueued {len(delta.added) + len(delta.modified)} summary jobs + "
          f"{len(stale_concepts)} concept refresh jobs.")
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
    print(f"Model: {manifest['model_used']}")
    print(f"Stats: {manifest['stats']}")
    print(f"Manifest size: ~{estimate_tokens(json.dumps(manifest))} tokens")
    if layout.log.exists():
        tail = layout.log.read_text().splitlines()[-10:]
        print("\nRecent log:")
        for line in tail:
            print(f"  {line}")
    return 0


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
    if concept_file.exists():
        tokens_est = estimate_tokens(concept_file.read_text())
    manifest["concepts"].append({
        "id": args.id,
        "file": rel_file,
        "topics": [t.strip() for t in args.topics.split(",")],
        "touches_sources": [t.strip() for t in args.touches.split(",")],
        "related_concepts": [],
        "tokens_est": tokens_est,
        "stale": False,
        "last_synthesized": now_iso(),
        "gaps": [],
    })
    save_manifest(layout, manifest)
    log_event(layout, f"add-concept: {args.id}")
    print(f"Added concept {args.id} ({tokens_est} tokens est.)")
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
                    c["tokens_est"] = estimate_tokens(cf.read_text())
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

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
