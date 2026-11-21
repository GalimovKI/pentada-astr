import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mail_search.cli import compare_runs
from mail_search.core.errors import ValidationError
from mail_search.evaluation.runner import read_predictions
from tests.fixtures.dataset import fixture


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = fixture(self.root / "data")

    def command(self, *args):
        return subprocess.run([sys.executable, "-m", "mail_search", *map(str, args)], capture_output=True, text=True)

    def test_installed_package_and_default_dataset_work_outside_repository(self):
        from mail_search.cli import DEFAULT_DATASET
        result = subprocess.run(
            [sys.executable, "-c", "from mail_search.cli import DEFAULT_DATASET; print(DEFAULT_DATASET)"],
            cwd=self.root, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(DEFAULT_DATASET.is_absolute())
        self.assertEqual(Path(result.stdout.strip()), DEFAULT_DATASET)

    def test_run_rescore_compare_and_prevent_overwrite(self):
        first, rescored = self.root / "first", self.root / "rescored"
        result = self.command("run", "--dataset", self.data, "--output", first, "--ks", 1, 10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.name for p in first.iterdir()}, {
            "run.json", "metrics.json", "predictions.jsonl", "per_query.jsonl", "report.md"})
        metadata = json.loads((first / "run.json").read_text())
        self.assertFalse(metadata["engine_latency"]["official_server_p99_measured"])
        self.assertEqual(metadata["engine"], "mail_search.search.event_aware:create_engine")
        self.assertEqual(metadata["engine_config"]["prospective_penalty"], 0.55)
        result = self.command("score", "--dataset", self.data, "--predictions", first / "predictions.jsonl",
                              "--output", rescored, "--ks", 1, 10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((first / "metrics.json").read_text()), json.loads((rescored / "metrics.json").read_text()))
        self.assertIn("+0.000000", compare_runs(first, rescored))
        result = self.command("run", "--dataset", self.data, "--output", first)
        self.assertEqual(result.returncode, 2)
        self.assertIn("already exists", result.stderr)

    def test_external_predictions_must_cover_all_queries(self):
        path = self.root / "predictions.jsonl"
        path.write_text('{"query_id":"q1","doc_ids":["d1"]}\n')
        result = self.command("score", "--dataset", self.data, "--predictions", path, "--output", self.root / "bad")
        self.assertEqual(result.returncode, 2)
        self.assertIn("coverage mismatch", result.stderr)
        self.assertFalse((self.root / "bad").exists())

    def test_search_returns_ranked_hits_for_explicit_mailbox_and_date(self):
        config = self.root / "stemmed.json"
        config.write_text('{"stemming": true, "date_mode": "contextual"}')
        result = self.command("search", "--dataset", self.data, "--config", config,
                              "--mailbox", "a", "--as-of", "2025-01-02", "чеками вчера")
        self.assertEqual(result.returncode, 0, result.stderr)
        hits = json.loads(result.stdout)
        self.assertEqual([hit["doc_id"] for hit in hits], ["d1"])
        self.assertGreater(hits[0]["score"], 0)

    def test_duplicate_query_in_predictions_rejected(self):
        path = self.root / "predictions.jsonl"
        path.write_text('{"query_id":"q1","doc_ids":[]}\n' * 2)
        with self.assertRaisesRegex(ValidationError, "duplicate query_id"):
            read_predictions(path)
