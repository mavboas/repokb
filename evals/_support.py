"""Shared helpers for the RepoKB eval suite.

Bootstraps sys.path so tests can `import compile_mod` (the orchestrator at
repokb/scripts/compile.py), provides temp-dir fixtures, and a subprocess
wrapper for end-to-end command tests.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "repokb" / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "compile.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import compile as compile_mod  # noqa: E402  (path bootstrap above)


def make_temp_repo(seed: Path | None = None) -> Path:
    """Create a fresh temp directory; optionally copy a fixture seed into it.

    Tests own cleanup via shutil.rmtree in tearDown (or a context manager).
    """
    tmp = Path(tempfile.mkdtemp(prefix="repokb_eval_"))
    if seed is not None:
        for src in seed.rglob("*"):
            if src.is_file():
                dst = tmp / src.relative_to(seed)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    return tmp


def run_compile(*args: str, cwd: Path | None = None,
                check: bool = True) -> subprocess.CompletedProcess:
    """Invoke compile.py as a subprocess. Returns the CompletedProcess."""
    cmd = [sys.executable, str(SCRIPT_PATH), *args]
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=check,
    )


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(layout, manifest: dict) -> None:
    """Write a MANIFEST dict to disk at layout.manifest, creating .repokb/ if needed."""
    layout.ensure()
    layout.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def load_fixture_manifest(name: str) -> dict:
    return load_json(FIXTURES / "manifests" / name)


def read_queue_jobs(layout) -> list[dict]:
    """Read all jobs from .work_queue.jsonl as a list of dicts."""
    if not layout.queue.exists():
        return []
    return [json.loads(line) for line in layout.queue.read_text().splitlines() if line.strip()]
