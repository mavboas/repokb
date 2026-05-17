"""Tests for compile.walk_sources, sha256_file, matches_any, summary_filename."""
from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from evals._support import compile_mod, make_temp_repo, write_file


class TestWalkSources(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _default_config(self) -> dict:
        cfg = dict(compile_mod.DEFAULT_CONFIG)
        cfg["exclude_globs"] = list(cfg["exclude_globs"])
        return cfg

    def test_finds_all_files_by_default(self):
        write_file(self.tmp / "a.py", "x = 1")
        write_file(self.tmp / "b.md", "hello")
        result = compile_mod.walk_sources(self.tmp, self._default_config())
        paths = {s["path"] for s in result}
        self.assertEqual(paths, {"a.py", "b.md"})

    def test_each_source_has_required_fields(self):
        write_file(self.tmp / "x.py", "content")
        result = compile_mod.walk_sources(self.tmp, self._default_config())
        self.assertEqual(len(result), 1)
        s = result[0]
        for field in ("path", "sha256", "bytes", "mtime", "type"):
            self.assertIn(field, s)
        self.assertEqual(len(s["sha256"]), 64, "sha256 must be 64 hex chars")
        self.assertEqual(s["type"], "py")
        self.assertEqual(s["bytes"], len("content"))

    def test_uses_forward_slash_paths(self):
        write_file(self.tmp / "src" / "deep" / "x.py", "y = 1")
        result = compile_mod.walk_sources(self.tmp, self._default_config())
        self.assertEqual(result[0]["path"], "src/deep/x.py")

    def test_excludes_repokb_directory(self):
        write_file(self.tmp / "src.py", "x")
        write_file(self.tmp / ".repokb" / "MANIFEST.json", "{}")
        result = compile_mod.walk_sources(self.tmp, self._default_config())
        paths = {s["path"] for s in result}
        self.assertEqual(paths, {"src.py"})

    def test_excludes_git_directory(self):
        write_file(self.tmp / "src.py", "x")
        write_file(self.tmp / ".git" / "HEAD", "ref: refs/heads/main")
        result = compile_mod.walk_sources(self.tmp, self._default_config())
        self.assertEqual({s["path"] for s in result}, {"src.py"})

    def test_excludes_lockfiles(self):
        write_file(self.tmp / "package.json", "{}")
        write_file(self.tmp / "package-lock.json", "{}")
        write_file(self.tmp / "poetry.lock", "")
        result = compile_mod.walk_sources(self.tmp, self._default_config())
        self.assertEqual({s["path"] for s in result}, {"package.json"})

    def test_custom_include_filter(self):
        write_file(self.tmp / "a.py", "x")
        write_file(self.tmp / "b.md", "y")
        cfg = self._default_config()
        cfg["include_globs"] = ["*.py"]
        result = compile_mod.walk_sources(self.tmp, cfg)
        self.assertEqual({s["path"] for s in result}, {"a.py"})

    def test_skips_binary_when_disabled(self):
        write_file(self.tmp / "doc.pdf", "%PDF-fake")
        write_file(self.tmp / "doc.md", "text")
        cfg = self._default_config()
        cfg["ingest_binary_docs"] = False
        result = compile_mod.walk_sources(self.tmp, cfg)
        self.assertEqual({s["path"] for s in result}, {"doc.md"})

    def test_includes_binary_when_enabled(self):
        write_file(self.tmp / "doc.pdf", "%PDF-fake")
        cfg = self._default_config()
        cfg["ingest_binary_docs"] = True
        result = compile_mod.walk_sources(self.tmp, cfg)
        self.assertEqual({s["path"] for s in result}, {"doc.pdf"})

    def test_same_content_same_hash(self):
        write_file(self.tmp / "a.py", "identical")
        write_file(self.tmp / "b.py", "identical")
        result = compile_mod.walk_sources(self.tmp, self._default_config())
        hashes = {s["path"]: s["sha256"] for s in result}
        self.assertEqual(hashes["a.py"], hashes["b.py"])


class TestSha256File(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_known_hash(self):
        f = self.tmp / "x.txt"
        f.write_bytes(b"hello")
        # SHA256("hello") = 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
        self.assertEqual(
            compile_mod.sha256_file(f),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        )


class TestMatchesAny(unittest.TestCase):
    def test_matches_one(self):
        self.assertTrue(compile_mod.matches_any("a.py", ["*.py", "*.md"]))

    def test_matches_none(self):
        self.assertFalse(compile_mod.matches_any("a.py", ["*.md", "*.txt"]))

    def test_nested_glob(self):
        self.assertTrue(compile_mod.matches_any(".repokb/MANIFEST.json", [".repokb/**"]))


class TestSummaryFilename(unittest.TestCase):
    def test_slashes_to_double_underscore(self):
        self.assertEqual(
            compile_mod.summary_filename("src/auth/login.py"),
            "src__auth__login.py.md",
        )

    def test_no_slashes(self):
        self.assertEqual(compile_mod.summary_filename("README.md"), "README.md.md")


if __name__ == "__main__":
    unittest.main()
