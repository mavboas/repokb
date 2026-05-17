"""Tests for the <<source:>> directive parser, MANIFEST mirror, and lint rules
STRUCT-08 (orphan directive / out-of-bounds range) and STRUCT-09 (code-block
heavy concept)."""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from evals._support import (
    FIXTURES, compile_mod, load_fixture_manifest, make_temp_repo, run_compile,
    write_file, load_json,
)


class TestDirectiveParser(unittest.TestCase):
    def test_range_form(self):
        ds = compile_mod.parse_directives_from_text(
            "see <<source: src/a.py:42-67>> here"
        )
        self.assertEqual(ds, [{"path": "src/a.py", "start": 42, "end": 67}])

    def test_single_line_form(self):
        ds = compile_mod.parse_directives_from_text(
            "see <<source: src/a.py:42>>"
        )
        self.assertEqual(ds, [{"path": "src/a.py", "start": 42, "end": 42}])

    def test_whole_file_form(self):
        ds = compile_mod.parse_directives_from_text(
            "see <<source: src/a.py>>"
        )
        self.assertEqual(ds, [{"path": "src/a.py", "start": None, "end": None}])

    def test_tolerates_whitespace(self):
        ds = compile_mod.parse_directives_from_text(
            "<<source:   src/a.py : 100 - 120 >>"
        )
        self.assertEqual(ds, [{"path": "src/a.py", "start": 100, "end": 120}])

    def test_multiple_directives(self):
        ds = compile_mod.parse_directives_from_text(
            "alpha <<source: a.py:1-2>> beta <<source: b.py:5>>"
        )
        self.assertEqual(len(ds), 2)
        self.assertEqual(ds[0]["path"], "a.py")
        self.assertEqual(ds[1]["path"], "b.py")


class TestManifestMirror(unittest.TestCase):
    """manifest-add-concept must populate source_directives from the concept file."""

    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        run_compile("init", "--root", str(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_concept_parses_directives(self):
        concept_file = self.layout.concepts / "demo.md"
        concept_file.write_text(
            "# Demo concept\n\n"
            "See <<source: a.py:10-20>> and <<source: b.py:5>>.\n"
        )
        run_compile(
            "manifest-add-concept",
            "--root", str(self.tmp),
            "--id", "demo",
            "--topics", "demo",
            "--touches", "a.py,b.py",
            "--file", "concepts/demo.md",
        )
        m = json.loads(self.layout.manifest.read_text())
        c = next(c for c in m["concepts"] if c["id"] == "demo")
        self.assertEqual(len(c["source_directives"]), 2)
        paths = sorted(d["path"] for d in c["source_directives"])
        self.assertEqual(paths, ["a.py", "b.py"])


class TestLintStructOrphanDirective(unittest.TestCase):
    """STRUCT-08 should fire when a directive's path is not in touches_sources."""

    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        self.layout.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _install_manifest_with_orphan(self):
        m = compile_mod.empty_manifest(self.tmp)
        m["sources"] = [
            {"path": "a.py", "sha256": "h1", "bytes": 100,
             "mtime": "2026-01-01T00:00:00+00:00", "type": "py",
             "summary": "summaries/a.py.md", "tags": [],
             "signature_source": None, "sig_sha256": None},
        ]
        m["concepts"] = [{
            "id": "c1", "file": "concepts/c1.md", "topics": ["x"],
            "touches_sources": ["a.py"],
            "source_directives": [
                {"path": "a.py", "start": 1, "end": 5},
                {"path": "NOT_IN_TOUCHES.py", "start": 1, "end": 5},
            ],
            "related_concepts": [], "tokens_est": 500, "stale": False,
            "last_synthesized": "2026-01-01T00:00:00+00:00", "gaps": [],
        }]
        self.layout.manifest.write_text(json.dumps(m, indent=2))

    def test_orphan_directive_triggers_struct_08(self):
        self._install_manifest_with_orphan()
        result = run_compile("lint", "--root", str(self.tmp), check=False)
        self.assertIn("STRUCT-08", result.stdout)
        self.assertIn("NOT_IN_TOUCHES.py", result.stdout)


class TestLintStructOutOfBounds(unittest.TestCase):
    """STRUCT-08 also fires for line ranges exceeding the actual file length."""

    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        self.layout.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_out_of_bounds_triggers_struct_08(self):
        # Real 3-line file, directive points at lines 50-60
        write_file(self.tmp / "tiny.py", "a = 1\nb = 2\nc = 3\n")
        m = compile_mod.empty_manifest(self.tmp)
        m["sources"] = [{
            "path": "tiny.py", "sha256": "h", "bytes": 18,
            "mtime": "2026-01-01T00:00:00+00:00", "type": "py",
            "summary": "summaries/tiny.py.md", "tags": [],
            "signature_source": None, "sig_sha256": None,
        }]
        m["concepts"] = [{
            "id": "c1", "file": "concepts/c1.md", "topics": ["x"],
            "touches_sources": ["tiny.py"],
            "source_directives": [{"path": "tiny.py", "start": 50, "end": 60}],
            "related_concepts": [], "tokens_est": 500, "stale": False,
            "last_synthesized": "2026-01-01T00:00:00+00:00", "gaps": [],
        }]
        self.layout.manifest.write_text(json.dumps(m, indent=2))
        result = run_compile("lint", "--root", str(self.tmp), check=False)
        self.assertIn("STRUCT-08", result.stdout)
        self.assertIn("exceeds file length", result.stdout)


class TestLintStruct09CodeBlockHeavy(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        self.layout.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_six_code_blocks_triggers_struct_09(self):
        body = "# big concept\n\n" + "\n".join(
            f"```python\nx_{i} = {i}\n```" for i in range(6)
        )
        write_file(self.layout.concepts / "fat.md", body)
        m = compile_mod.empty_manifest(self.tmp)
        m["sources"] = [
            {"path": "a.py", "sha256": "h1", "bytes": 100,
             "mtime": "2026-01-01T00:00:00+00:00", "type": "py",
             "summary": "summaries/a.py.md", "tags": [],
             "signature_source": None, "sig_sha256": None},
        ]
        m["concepts"] = [{
            "id": "fat", "file": "concepts/fat.md", "topics": ["x"],
            "touches_sources": ["a.py"], "source_directives": [],
            "related_concepts": [], "tokens_est": 500, "stale": False,
            "last_synthesized": "2026-01-01T00:00:00+00:00", "gaps": [],
        }]
        self.layout.manifest.write_text(json.dumps(m, indent=2))
        result = run_compile("lint", "--root", str(self.tmp), check=False)
        self.assertIn("STRUCT-09", result.stdout)


class TestPerf04DeferRate(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        self.layout.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_high_defer_rate_triggers_perf_04(self):
        m = compile_mod.empty_manifest(self.tmp)
        m["stats"]["signature_defer_rate"] = 0.5
        self.layout.manifest.write_text(json.dumps(m, indent=2))
        result = run_compile("lint", "--root", str(self.tmp), check=False)
        self.assertIn("PERF-04", result.stdout)


if __name__ == "__main__":
    unittest.main()
