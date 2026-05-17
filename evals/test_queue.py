"""Tests for queue_append and queue_clear."""
from __future__ import annotations

import json
import shutil
import unittest

from evals._support import compile_mod, make_temp_repo


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_repo()
        self.layout = compile_mod.Layout(self.tmp)
        self.layout.ensure()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_writes_jsonl(self):
        compile_mod.queue_append(self.layout, {"job": "summarize", "path": "a.py"})
        compile_mod.queue_append(self.layout, {"job": "summarize", "path": "b.py"})
        lines = self.layout.queue.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            obj = json.loads(line)
            self.assertEqual(obj["job"], "summarize")

    def test_append_assigns_job_id_when_missing(self):
        compile_mod.queue_append(self.layout, {"job": "summarize", "path": "a.py"})
        obj = json.loads(self.layout.queue.read_text().splitlines()[0])
        self.assertIn("job_id", obj)
        self.assertTrue(obj["job_id"].startswith("j"))

    def test_append_preserves_explicit_job_id(self):
        compile_mod.queue_append(self.layout,
                                  {"job_id": "custom", "job": "summarize"})
        obj = json.loads(self.layout.queue.read_text().splitlines()[0])
        self.assertEqual(obj["job_id"], "custom")

    def test_job_ids_are_unique(self):
        for _ in range(10):
            compile_mod.queue_append(self.layout, {"job": "x"})
        ids = [json.loads(line)["job_id"]
               for line in self.layout.queue.read_text().splitlines()]
        self.assertEqual(len(set(ids)), 10)

    def test_clear_empties_both_files(self):
        compile_mod.queue_append(self.layout, {"job": "x"})
        self.layout.results.write_text('{"result": "ok"}\n')
        compile_mod.queue_clear(self.layout)
        self.assertEqual(self.layout.queue.read_text(), "")
        self.assertEqual(self.layout.results.read_text(), "")


if __name__ == "__main__":
    unittest.main()
