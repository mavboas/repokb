"""Tests for cmd_lint — drives each rule via a fixture MANIFEST."""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from evals._support import (
    FIXTURES, compile_mod, load_fixture_manifest, make_temp_repo, run_compile,
)


def _install_fixture_manifest(layout, name: str) -> dict:
    """Copy a fixture MANIFEST into layout.manifest, rewriting `root` so the
    on-disk root matches the temp dir (lint doesn't actually read sources,
    but keep it tidy)."""
    m = load_fixture_manifest(name)
    m["root"] = str(layout.root)
    layout.ensure()
    layout.manifest.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


class TestLintRules(unittest.TestCase):
    """Each test asserts the target rule fires for its fixture. We don't
    assert that NO other rules fire — some fixtures (PERF-02, PERF-03) also
    trip PERF-01 by construction (a big concept list is a big MANIFEST).
    """

    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _lint(self) -> str:
        result = run_compile("lint", "--root", str(self.tmp), check=False)
        return result.stdout

    def test_struct_01_stale_concept(self):
        _install_fixture_manifest(self.layout, "stale_concept.json")
        out = self._lint()
        self.assertIn("STRUCT-01", out)
        self.assertIn("c1", out)

    def test_struct_04_oversized_concept(self):
        _install_fixture_manifest(self.layout, "oversized_concept.json")
        out = self._lint()
        self.assertIn("STRUCT-04", out)
        self.assertIn("big", out)

    def test_struct_05_single_source_concept(self):
        _install_fixture_manifest(self.layout, "single_source.json")
        out = self._lint()
        self.assertIn("STRUCT-05", out)
        self.assertIn("thin", out)

    def test_struct_06_unreferenced_source(self):
        _install_fixture_manifest(self.layout, "unreferenced_source.json")
        out = self._lint()
        self.assertIn("STRUCT-06", out)
        self.assertIn("orphan.py", out)

    def test_perf_01_manifest_bloat(self):
        _install_fixture_manifest(self.layout, "manifest_bloat.json")
        out = self._lint()
        self.assertIn("PERF-01", out)

    def test_perf_02_too_many_concepts(self):
        _install_fixture_manifest(self.layout, "too_many_concepts.json")
        out = self._lint()
        self.assertIn("PERF-02", out)
        self.assertIn("> 80", out)

    def test_perf_03_high_fanout(self):
        _install_fixture_manifest(self.layout, "high_fanout.json")
        out = self._lint()
        self.assertIn("PERF-03", out)
        self.assertIn("fanout", out)

    def test_know_01_declared_gap(self):
        _install_fixture_manifest(self.layout, "declared_gap.json")
        out = self._lint()
        self.assertIn("KNOW-01", out)


class TestLintHealthy(unittest.TestCase):
    """A clean MANIFEST should produce zero issues."""

    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        self.layout.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_manifest_reports_healthy(self):
        m = compile_mod.empty_manifest(self.tmp)
        m["sources"] = [
            {"path": "a.py", "sha256": "h1", "bytes": 100,
             "mtime": "2026-01-01T00:00:00+00:00", "type": "py",
             "summary": "summaries/a.py.md", "tags": []},
            {"path": "b.py", "sha256": "h2", "bytes": 100,
             "mtime": "2026-01-01T00:00:00+00:00", "type": "py",
             "summary": "summaries/b.py.md", "tags": []},
        ]
        m["concepts"] = [
            {"id": "c1", "file": "concepts/c1.md", "topics": ["t1"],
             "touches_sources": ["a.py", "b.py"], "related_concepts": [],
             "tokens_est": 500, "stale": False,
             "last_synthesized": "2026-01-01T00:00:00+00:00", "gaps": []},
        ]
        self.layout.manifest.write_text(json.dumps(m, indent=2), encoding="utf-8")
        result = run_compile("lint", "--root", str(self.tmp), check=False)
        self.assertIn("healthy", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
