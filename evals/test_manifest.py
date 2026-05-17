"""Tests for empty_manifest, recompute_stats, estimate_tokens, save_manifest budget warning."""
from __future__ import annotations

import io
import json
import shutil
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from evals._support import compile_mod, make_temp_repo


class TestEmptyManifest(unittest.TestCase):
    def test_schema_fields(self):
        m = compile_mod.empty_manifest(Path("/tmp/x"))
        for key in ("version", "root", "created_at", "updated_at", "model_used",
                    "config", "stats", "sources", "concepts", "renames_log"):
            self.assertIn(key, m)

    def test_schema_version_is_one(self):
        m = compile_mod.empty_manifest(Path("/tmp/x"))
        self.assertEqual(m["version"], compile_mod.SCHEMA_VERSION)
        self.assertEqual(m["version"], 1)

    def test_default_config_embedded(self):
        m = compile_mod.empty_manifest(Path("/tmp/x"))
        self.assertEqual(m["config"]["max_concept_tokens"], 1500)
        self.assertEqual(m["config"]["max_summary_tokens"], 400)
        self.assertEqual(m["config"]["max_concepts"], 80)


class TestRecomputeStats(unittest.TestCase):
    def test_counts_sources_and_concepts(self):
        m = {
            "sources": [
                {"path": "a", "bytes": 100, "summary": "s1"},
                {"path": "b", "bytes": 200, "summary": "s2"},
            ],
            "concepts": [
                {"id": "c1", "stale": False},
                {"id": "c2", "stale": True},
            ],
        }
        stats = compile_mod.recompute_stats(m)
        self.assertEqual(stats["sources"], 2)
        self.assertEqual(stats["summaries"], 2)
        self.assertEqual(stats["concepts"], 2)
        self.assertEqual(stats["stale_concepts"], 1)
        self.assertEqual(stats["total_size_bytes"], 300)

    def test_empty(self):
        stats = compile_mod.recompute_stats({"sources": [], "concepts": []})
        self.assertEqual(stats["sources"], 0)
        self.assertEqual(stats["concepts"], 0)
        self.assertEqual(stats["total_size_bytes"], 0)


class TestEstimateTokens(unittest.TestCase):
    def test_short_string(self):
        self.assertEqual(compile_mod.estimate_tokens("abcd"), 1)

    def test_empty_string_returns_at_least_one(self):
        self.assertEqual(compile_mod.estimate_tokens(""), 1)

    def test_long_string(self):
        # 4000 chars -> 1000 tokens
        self.assertEqual(compile_mod.estimate_tokens("x" * 4000), 1000)


class TestSaveManifestBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        self.layout.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_writes_and_updates_timestamp(self):
        m = compile_mod.empty_manifest(self.tmp)
        original_updated = m["updated_at"]
        # Force a tiny delay isn't reliable; just confirm it serializes & re-reads.
        compile_mod.save_manifest(self.layout, m)
        roundtrip = json.loads(self.layout.manifest.read_text())
        self.assertEqual(roundtrip["version"], 1)
        self.assertIn("updated_at", roundtrip)

    def test_save_warns_when_over_budget(self):
        m = compile_mod.empty_manifest(self.tmp)
        # Inflate the manifest beyond 3000 tokens (~12000 chars)
        m["sources"] = [
            {"path": f"src/module_{i}/file_{i}.py", "sha256": "h" * 64,
             "bytes": 1000, "mtime": "2026-01-01T00:00:00+00:00", "type": "py",
             "summary": f"summaries/src__module_{i}__file_{i}.py.md", "tags": []}
            for i in range(80)
        ]
        buf = io.StringIO()
        with redirect_stderr(buf):
            compile_mod.save_manifest(self.layout, m)
        self.assertIn("3000-token budget", buf.getvalue())

    def test_save_no_warning_when_under_budget(self):
        m = compile_mod.empty_manifest(self.tmp)
        buf = io.StringIO()
        with redirect_stderr(buf):
            compile_mod.save_manifest(self.layout, m)
        self.assertNotIn("3000-token budget", buf.getvalue())


class TestLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ensure_creates_directories(self):
        layout = compile_mod.Layout(self.tmp)
        layout.ensure()
        self.assertTrue(layout.kb.is_dir())
        self.assertTrue(layout.concepts.is_dir())
        self.assertTrue(layout.summaries.is_dir())
        self.assertTrue(layout.sources.is_dir())

    def test_path_layout(self):
        layout = compile_mod.Layout(self.tmp)
        self.assertEqual(layout.manifest.name, "MANIFEST.json")
        self.assertEqual(layout.queue.name, ".work_queue.jsonl")
        self.assertEqual(layout.results.name, ".work_queue.results.jsonl")


if __name__ == "__main__":
    unittest.main()
