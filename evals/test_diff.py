"""Tests for compile.diff_sources — added/removed/modified/renamed/unchanged."""
from __future__ import annotations

import unittest

from evals._support import compile_mod


def _src(path: str, sha: str, **kw) -> dict:
    return {"path": path, "sha256": sha, "bytes": 100,
            "mtime": "2026-01-01T00:00:00+00:00", "type": "py", **kw}


class TestDiffSources(unittest.TestCase):
    def test_unchanged(self):
        old = [_src("a.py", "h1")]
        new = [_src("a.py", "h1")]
        d = compile_mod.diff_sources(old, new)
        self.assertEqual(len(d.unchanged), 1)
        self.assertEqual(d.unchanged[0]["path"], "a.py")
        self.assertEqual(d.added, [])
        self.assertEqual(d.removed, [])
        self.assertEqual(d.modified, [])
        self.assertEqual(d.renamed, [])

    def test_added(self):
        old = [_src("a.py", "h1")]
        new = [_src("a.py", "h1"), _src("b.py", "h2")]
        d = compile_mod.diff_sources(old, new)
        self.assertEqual(len(d.added), 1)
        self.assertEqual(d.added[0]["path"], "b.py")
        self.assertEqual(len(d.unchanged), 1)
        self.assertEqual(d.removed, [])

    def test_removed(self):
        old = [_src("a.py", "h1"), _src("b.py", "h2")]
        new = [_src("a.py", "h1")]
        d = compile_mod.diff_sources(old, new)
        self.assertEqual(len(d.removed), 1)
        self.assertEqual(d.removed[0]["path"], "b.py")
        self.assertEqual(len(d.unchanged), 1)
        self.assertEqual(d.added, [])

    def test_modified(self):
        old = [_src("a.py", "h1")]
        new = [_src("a.py", "h1_changed")]
        d = compile_mod.diff_sources(old, new)
        self.assertEqual(len(d.modified), 1)
        self.assertEqual(d.modified[0]["path"], "a.py")
        self.assertEqual(d.modified[0]["sha256"], "h1_changed")
        self.assertEqual(d.unchanged, [])

    def test_renamed_detected_by_hash(self):
        old = [_src("old_name.py", "h1")]
        new = [_src("new_name.py", "h1")]
        d = compile_mod.diff_sources(old, new)
        self.assertEqual(len(d.renamed), 1)
        old_e, new_e = d.renamed[0]
        self.assertEqual(old_e["path"], "old_name.py")
        self.assertEqual(new_e["path"], "new_name.py")
        # rename must NOT also count as added/removed
        self.assertEqual(d.added, [])
        self.assertEqual(d.removed, [])

    def test_rename_not_triggered_if_old_still_exists(self):
        """If a file with the same hash already exists at the old path, the new
        path is an addition (copy), not a rename."""
        old = [_src("a.py", "h1")]
        new = [_src("a.py", "h1"), _src("a_copy.py", "h1")]
        d = compile_mod.diff_sources(old, new)
        self.assertEqual(len(d.added), 1)
        self.assertEqual(d.added[0]["path"], "a_copy.py")
        self.assertEqual(d.renamed, [])

    def test_mixed_delta(self):
        old = [_src("keep.py", "h1"),
               _src("change.py", "h2"),
               _src("gone.py", "h3"),
               _src("rename_me.py", "h4")]
        new = [_src("keep.py", "h1"),
               _src("change.py", "h2_new"),
               _src("rename_me_now.py", "h4"),
               _src("brand_new.py", "h5")]
        d = compile_mod.diff_sources(old, new)
        self.assertEqual([s["path"] for s in d.unchanged], ["keep.py"])
        self.assertEqual([s["path"] for s in d.modified], ["change.py"])
        self.assertEqual([s["path"] for s in d.removed], ["gone.py"])
        self.assertEqual([s["path"] for s in d.added], ["brand_new.py"])
        self.assertEqual(len(d.renamed), 1)
        self.assertEqual(d.renamed[0][0]["path"], "rename_me.py")
        self.assertEqual(d.renamed[0][1]["path"], "rename_me_now.py")

    def test_empty_old(self):
        d = compile_mod.diff_sources([], [_src("a.py", "h1")])
        self.assertEqual(len(d.added), 1)
        self.assertEqual(d.removed, [])

    def test_empty_new(self):
        d = compile_mod.diff_sources([_src("a.py", "h1")], [])
        self.assertEqual(len(d.removed), 1)
        self.assertEqual(d.added, [])


if __name__ == "__main__":
    unittest.main()
