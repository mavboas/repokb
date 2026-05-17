"""Integration tests for the manifest-* helper subcommands."""
from __future__ import annotations

import json
import shutil
import unittest

from evals._support import (
    FIXTURES, compile_mod, make_temp_repo, run_compile,
)


class TestManifestAddConcept(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo(FIXTURES / "minimal_repo")
        self.layout = compile_mod.Layout(self.tmp)
        run_compile("init", "--root", str(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _manifest(self) -> dict:
        return json.loads(self.layout.manifest.read_text())

    def test_add_concept_appears_in_manifest(self):
        run_compile(
            "manifest-add-concept",
            "--root", str(self.tmp),
            "--id", "auth-flow",
            "--topics", "authentication,oauth",
            "--touches", "src/auth/login.py,src/auth/oauth.py",
            "--file", "concepts/auth-flow.md",
        )
        m = self._manifest()
        ids = [c["id"] for c in m["concepts"]]
        self.assertIn("auth-flow", ids)
        concept = next(c for c in m["concepts"] if c["id"] == "auth-flow")
        self.assertEqual(concept["topics"], ["authentication", "oauth"])
        self.assertEqual(set(concept["touches_sources"]),
                         {"src/auth/login.py", "src/auth/oauth.py"})
        self.assertFalse(concept["stale"])

    def test_add_concept_with_existing_file_counts_tokens(self):
        concept_file = self.layout.concepts / "auth-flow.md"
        concept_file.write_text("a" * 400)  # 100 tokens roughly
        run_compile(
            "manifest-add-concept",
            "--root", str(self.tmp),
            "--id", "auth-flow",
            "--topics", "x",
            "--touches", "src/auth/login.py,src/auth/oauth.py",
            "--file", "concepts/auth-flow.md",
        )
        m = self._manifest()
        c = next(c for c in m["concepts"] if c["id"] == "auth-flow")
        self.assertGreater(c["tokens_est"], 50)

    def test_add_duplicate_concept_fails(self):
        args = [
            "manifest-add-concept", "--root", str(self.tmp),
            "--id", "auth-flow", "--topics", "x", "--touches", "a,b",
            "--file", "concepts/auth-flow.md",
        ]
        run_compile(*args)
        result = run_compile(*args, check=False)
        self.assertNotEqual(result.returncode, 0)


class TestManifestSetStale(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo(FIXTURES / "minimal_repo")
        self.layout = compile_mod.Layout(self.tmp)
        run_compile("init", "--root", str(self.tmp))
        run_compile(
            "manifest-add-concept", "--root", str(self.tmp),
            "--id", "c1", "--topics", "x",
            "--touches", "src/auth/login.py,src/auth/oauth.py",
            "--file", "concepts/c1.md",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_set_stale_true(self):
        run_compile("manifest-set-stale", "--root", str(self.tmp),
                    "--concept", "c1", "--stale", "true")
        m = json.loads(self.layout.manifest.read_text())
        self.assertTrue(next(c for c in m["concepts"] if c["id"] == "c1")["stale"])

    def test_set_stale_false_updates_synthesized_timestamp(self):
        run_compile("manifest-set-stale", "--root", str(self.tmp),
                    "--concept", "c1", "--stale", "true")
        run_compile("manifest-set-stale", "--root", str(self.tmp),
                    "--concept", "c1", "--stale", "false")
        m = json.loads(self.layout.manifest.read_text())
        c = next(c for c in m["concepts"] if c["id"] == "c1")
        self.assertFalse(c["stale"])
        self.assertIn("last_synthesized", c)

    def test_set_stale_unknown_concept_fails(self):
        result = run_compile("manifest-set-stale", "--root", str(self.tmp),
                             "--concept", "nope", "--stale", "true",
                             check=False)
        self.assertNotEqual(result.returncode, 0)


class TestManifestRemoveSource(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo(FIXTURES / "minimal_repo")
        self.layout = compile_mod.Layout(self.tmp)
        run_compile("init", "--root", str(self.tmp))
        run_compile(
            "manifest-add-concept", "--root", str(self.tmp),
            "--id", "auth-flow", "--topics", "x",
            "--touches", "src/auth/login.py,src/auth/oauth.py",
            "--file", "concepts/auth-flow.md",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_remove_source_drops_from_manifest(self):
        run_compile("manifest-remove-source", "--root", str(self.tmp),
                    "--path", "src/auth/oauth.py")
        m = json.loads(self.layout.manifest.read_text())
        paths = [s["path"] for s in m["sources"]]
        self.assertNotIn("src/auth/oauth.py", paths)

    def test_remove_source_cascades_stale(self):
        run_compile("manifest-remove-source", "--root", str(self.tmp),
                    "--path", "src/auth/oauth.py")
        m = json.loads(self.layout.manifest.read_text())
        c = next(c for c in m["concepts"] if c["id"] == "auth-flow")
        self.assertTrue(c["stale"])
        self.assertNotIn("src/auth/oauth.py", c["touches_sources"])

    def test_remove_unknown_source_fails(self):
        result = run_compile("manifest-remove-source", "--root", str(self.tmp),
                             "--path", "no/such/file.py", check=False)
        self.assertNotEqual(result.returncode, 0)


class TestPruneOrphanSummary(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo(FIXTURES / "minimal_repo")
        self.layout = compile_mod.Layout(self.tmp)
        run_compile("init", "--root", str(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prune_removes_summary_file(self):
        orphan = self.layout.summaries / "ghost.py.md"
        orphan.write_text("# Ghost\n")
        self.assertTrue(orphan.exists())
        run_compile("prune-orphan-summary", "--root", str(self.tmp),
                    "--path", "summaries/ghost.py.md")
        self.assertFalse(orphan.exists())

    def test_prune_nonexistent_fails(self):
        result = run_compile("prune-orphan-summary", "--root", str(self.tmp),
                             "--path", "summaries/nope.md", check=False)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
