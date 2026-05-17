"""Integration tests for `compile.py init` — drives a real subprocess against
the minimal_repo fixture and verifies on-disk state + the queued work."""
from __future__ import annotations

import json
import shutil
import unittest

from evals._support import (
    FIXTURES, compile_mod, make_temp_repo, read_queue_jobs, run_compile,
)


class TestCmdInit(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo(FIXTURES / "minimal_repo")
        self.layout = compile_mod.Layout(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_init_creates_kb_dirs(self):
        run_compile("init", "--root", str(self.tmp))
        self.assertTrue(self.layout.kb.is_dir())
        self.assertTrue(self.layout.concepts.is_dir())
        self.assertTrue(self.layout.summaries.is_dir())
        self.assertTrue(self.layout.sources.is_dir())

    def test_init_writes_manifest(self):
        run_compile("init", "--root", str(self.tmp))
        self.assertTrue(self.layout.manifest.is_file())
        m = json.loads(self.layout.manifest.read_text())
        self.assertEqual(m["version"], 1)
        self.assertEqual(len(m["sources"]), 8,
                         "minimal_repo has 8 source files")

    def test_init_queues_one_summary_job_per_source(self):
        run_compile("init", "--root", str(self.tmp))
        jobs = read_queue_jobs(self.layout)
        summary_jobs = [j for j in jobs if j["job"] == "summarize"]
        self.assertEqual(len(summary_jobs), 8)

    def test_init_queues_exactly_one_concept_init_job(self):
        run_compile("init", "--root", str(self.tmp))
        jobs = read_queue_jobs(self.layout)
        concept_jobs = [j for j in jobs if j["job"] == "concept_init"]
        self.assertEqual(len(concept_jobs), 1)
        self.assertEqual(
            len(concept_jobs[0]["summary_paths"]), 8,
            "concept_init job should reference all 8 summaries",
        )

    def test_init_summary_paths_use_double_underscore(self):
        run_compile("init", "--root", str(self.tmp))
        jobs = read_queue_jobs(self.layout)
        summary_jobs = [j for j in jobs if j["job"] == "summarize"]
        for j in summary_jobs:
            self.assertIn("summaries/", j["out_path"])
            self.assertNotIn("/", j["out_path"].rsplit("summaries/", 1)[1])

    def test_init_refuses_when_manifest_exists(self):
        run_compile("init", "--root", str(self.tmp))
        result = run_compile("init", "--root", str(self.tmp), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stdout + result.stderr)

    def test_init_reuse_config_succeeds_when_manifest_exists(self):
        run_compile("init", "--root", str(self.tmp))
        # Mutate config to confirm it's preserved across re-init
        m = json.loads(self.layout.manifest.read_text())
        m["config"]["marginal_sources"] = ["tests/test_auth.py"]
        self.layout.manifest.write_text(json.dumps(m, indent=2))
        run_compile("init", "--root", str(self.tmp), "--reuse-config")
        reloaded = json.loads(self.layout.manifest.read_text())
        self.assertEqual(reloaded["config"]["marginal_sources"],
                         ["tests/test_auth.py"])


class TestCmdInspect(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo(FIXTURES / "minimal_repo")
        self.layout = compile_mod.Layout(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inspect_prints_stats(self):
        run_compile("init", "--root", str(self.tmp))
        result = run_compile("inspect", "--root", str(self.tmp))
        self.assertIn("Stats:", result.stdout)
        self.assertIn("Manifest size:", result.stdout)


if __name__ == "__main__":
    unittest.main()
