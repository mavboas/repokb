"""Integration tests for `compile.py update` — staleness cascade, rename pathway."""
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from evals._support import (
    FIXTURES, compile_mod, make_temp_repo, read_queue_jobs, run_compile,
)


class TestCmdUpdateBase(unittest.TestCase):
    """Set up: init the KB, then manually register one concept that touches
    src/auth/login.py and src/auth/oauth.py — so we can test staleness."""

    def setUp(self):
        self.tmp = make_temp_repo(FIXTURES / "minimal_repo")
        self.layout = compile_mod.Layout(self.tmp)
        run_compile("init", "--root", str(self.tmp))
        # Register an auth-flow concept
        concept_md = self.layout.concepts / "auth-flow.md"
        concept_md.write_text("# Auth Flow\n\nstub content.\n")
        run_compile(
            "manifest-add-concept",
            "--root", str(self.tmp),
            "--id", "auth-flow",
            "--topics", "authentication,login,oauth",
            "--touches", "src/auth/login.py,src/auth/oauth.py",
            "--file", "concepts/auth-flow.md",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _manifest(self) -> dict:
        return json.loads(self.layout.manifest.read_text())


class TestCmdUpdateChange(TestCmdUpdateBase):
    def test_modify_file_marks_touching_concept_stale(self):
        # Modify oauth.py
        (self.tmp / "src" / "auth" / "oauth.py").write_text(
            "# changed content\nprint('new')\n"
        )
        run_compile("update", "--root", str(self.tmp))
        m = self._manifest()
        concept = next(c for c in m["concepts"] if c["id"] == "auth-flow")
        self.assertTrue(concept["stale"])

    def test_modify_unrelated_file_does_not_mark_concept_stale(self):
        (self.tmp / "src" / "db" / "cache.py").write_text("# changed\n")
        run_compile("update", "--root", str(self.tmp))
        m = self._manifest()
        concept = next(c for c in m["concepts"] if c["id"] == "auth-flow")
        self.assertFalse(concept["stale"])

    def test_modified_file_gets_summary_job(self):
        (self.tmp / "src" / "auth" / "oauth.py").write_text("# new\n")
        run_compile("update", "--root", str(self.tmp))
        jobs = read_queue_jobs(self.layout)
        summary_paths = [j["source_path"] for j in jobs
                         if j["job"] == "summarize"]
        self.assertIn("src/auth/oauth.py", summary_paths)
        # Unchanged files should NOT be re-summarized
        self.assertNotIn("src/db/cache.py", summary_paths)

    def test_modified_file_triggers_concept_refresh(self):
        (self.tmp / "src" / "auth" / "oauth.py").write_text("# new\n")
        run_compile("update", "--root", str(self.tmp))
        jobs = read_queue_jobs(self.layout)
        refresh_jobs = [j for j in jobs if j["job"] == "concept_refresh"]
        self.assertEqual(len(refresh_jobs), 1)
        self.assertEqual(refresh_jobs[0]["concept_id"], "auth-flow")


class TestCmdUpdateRename(TestCmdUpdateBase):
    def test_rename_updates_touches_sources_and_renames_summary(self):
        old = self.tmp / "src" / "auth" / "oauth.py"
        new = self.tmp / "src" / "auth" / "oauth_v2.py"
        # Seed the prior summary file (init only queues the job; nothing wrote it)
        old_summary = self.layout.summaries / "src__auth__oauth.py.md"
        old_summary.write_text("# Stub summary\n")
        # Update MANIFEST so the source's summary entry points to the file we just wrote
        m = self._manifest()
        for s in m["sources"]:
            if s["path"] == "src/auth/oauth.py":
                s["summary"] = "summaries/src__auth__oauth.py.md"
        self.layout.manifest.write_text(json.dumps(m, indent=2))
        # Now rename on disk
        old.rename(new)
        run_compile("update", "--root", str(self.tmp))

        m2 = self._manifest()
        paths = [s["path"] for s in m2["sources"]]
        self.assertIn("src/auth/oauth_v2.py", paths)
        self.assertNotIn("src/auth/oauth.py", paths)

        concept = next(c for c in m2["concepts"] if c["id"] == "auth-flow")
        self.assertIn("src/auth/oauth_v2.py", concept["touches_sources"])
        self.assertNotIn("src/auth/oauth.py", concept["touches_sources"])

        # Summary file should have been renamed on disk, not re-summarized
        new_summary = self.layout.summaries / "src__auth__oauth_v2.py.md"
        self.assertTrue(new_summary.is_file())
        self.assertFalse(old_summary.is_file())

        # Rename should be logged
        self.assertEqual(len(m2["renames_log"]), 1)
        self.assertEqual(m2["renames_log"][0]["from"], "src/auth/oauth.py")
        self.assertEqual(m2["renames_log"][0]["to"], "src/auth/oauth_v2.py")

    def test_rename_does_not_queue_summarize_for_renamed_file(self):
        (self.tmp / "src" / "auth" / "oauth.py").rename(
            self.tmp / "src" / "auth" / "oauth_v2.py"
        )
        run_compile("update", "--root", str(self.tmp))
        jobs = read_queue_jobs(self.layout)
        summary_paths = [j["source_path"] for j in jobs
                         if j["job"] == "summarize"]
        self.assertNotIn("src/auth/oauth_v2.py", summary_paths)
        self.assertNotIn("src/auth/oauth.py", summary_paths)


class TestCmdUpdateDelete(TestCmdUpdateBase):
    def test_delete_removes_from_sources_and_cascades_stale(self):
        (self.tmp / "src" / "auth" / "oauth.py").unlink()
        run_compile("update", "--root", str(self.tmp))
        m = self._manifest()
        paths = [s["path"] for s in m["sources"]]
        self.assertNotIn("src/auth/oauth.py", paths)
        concept = next(c for c in m["concepts"] if c["id"] == "auth-flow")
        self.assertTrue(concept["stale"])
        # touches_sources should drop the deleted path
        self.assertNotIn("src/auth/oauth.py", concept["touches_sources"])


class TestCmdUpdateAdd(TestCmdUpdateBase):
    def test_added_file_appears_in_sources(self):
        (self.tmp / "src" / "auth" / "tokens.py").write_text(
            "def refresh(): pass\n"
        )
        run_compile("update", "--root", str(self.tmp))
        m = self._manifest()
        paths = [s["path"] for s in m["sources"]]
        self.assertIn("src/auth/tokens.py", paths)

    def test_added_file_gets_summary_job(self):
        (self.tmp / "src" / "auth" / "tokens.py").write_text("x = 1\n")
        run_compile("update", "--root", str(self.tmp))
        jobs = read_queue_jobs(self.layout)
        summary_paths = [j["source_path"] for j in jobs
                         if j["job"] == "summarize"]
        self.assertIn("src/auth/tokens.py", summary_paths)


if __name__ == "__main__":
    unittest.main()
