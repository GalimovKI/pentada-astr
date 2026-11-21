import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from mailsearch.baseline import BM25Engine, target_day
from mailsearch.cli import compare_runs
from mailsearch.data import ValidationError, load_dataset
from mailsearch.evaluation import evaluate, read_predictions, run_engine, validate_ranking
from mailsearch.metrics import metrics_at_k, percentile
from mailsearch.models import SearchHit, SearchRequest


def fixture(root: Path, *, documents=None, queries=None, qrels=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    documents = documents if documents is not None else [
        {"doc_id": did, "synthetic_user": user, "doc": "Чек магазина. Оплата покупок.", "doc_dt": dt}
        for did, user, dt in (("d1", "a", "2025-01-01"), ("d2", "a", "2025-01-02"),
                              ("future", "a", "2025-01-03"), ("unknown-date", "a", None),
                              ("other-box", "b", "2025-01-01"))]
    queries = queries if queries is not None else [
        {"query_id": "q1", "synthetic_user": "a", "query": "чек вчера", "query_date": "2025-01-02"},
        {"query_id": "q2", "synthetic_user": "a", "query": "чек", "query_date": "2025-01-02"}]
    qrels = qrels if qrels is not None else [
        {"query_id": "q1", "doc_id": "d1", "relevance": 1},
        {"query_id": "q2", "doc_id": "d1", "relevance": 1},
        {"query_id": "q2", "doc_id": "d2", "relevance": 1}]
    (root / "README.md").write_text("Synthetic test fixture\n", encoding="utf-8")
    hashes = {"README.md": hashlib.sha256((root / "README.md").read_bytes()).hexdigest()}
    for name, rows in (("documents.jsonl", documents), ("queries_dev.jsonl", queries), ("qrels_dev.jsonl", qrels)):
        data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
        (root / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    (root / "manifest.json").write_text(json.dumps({
        "documents": len(documents), "queries": len(queries), "qrels": len(qrels), "sha256": hashes,
    }), encoding="utf-8")
    return root


class MetricTests(unittest.TestCase):
    def test_hand_calculated_ranking(self):
        ranking, qrels = ["unjudged", "r2", "r1"], {"r1": 1, "r2": 1}
        self.assertEqual(metrics_at_k(ranking, qrels, 1), {"recall": 0, "ndcg": 0, "mrr": 0})
        values = metrics_at_k(ranking, qrels, 2)
        self.assertEqual(values["recall"], 0.5)
        self.assertEqual(values["mrr"], 0.5)
        self.assertAlmostEqual(values["ndcg"], (1 / math.log2(3)) / (1 + 1 / math.log2(3)))
        values = metrics_at_k(ranking, qrels, 3)
        self.assertEqual(values["recall"], 1)
        self.assertAlmostEqual(values["ndcg"], (1 / math.log2(3) + 0.5) / (1 + 1 / math.log2(3)))

    def test_short_perfect_ranking_and_no_relevant_documents(self):
        self.assertEqual(metrics_at_k(["r1"], {"r1": 1}, 10), {"recall": 1, "ndcg": 1, "mrr": 1})
        self.assertEqual(metrics_at_k(["x"], {}, 10), {"recall": 0, "ndcg": 0, "mrr": 0})

    def test_nearest_rank_small_sample(self):
        self.assertEqual(percentile(list(range(1, 100)), 0.99), 99)
        self.assertIsNone(percentile([], 0.99))


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture(Path(self.temp.name) / "data")

    def test_zip_and_directory_have_same_fingerprint(self):
        archive = Path(self.temp.name) / "data.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for path in self.root.iterdir():
                z.write(path, path.name)
        a, b = load_dataset(self.root), load_dataset(archive)
        self.assertEqual(a.summary, b.summary)
        self.assertEqual(a.summary["documents"], 5)
        self.assertEqual(a.summary["unknown_document_dates"], 1)

    def test_integrity_failure_precedes_evaluation(self):
        with (self.root / "documents.jsonl").open("ab") as f:
            f.write(b"\n")
        with self.assertRaisesRegex(ValidationError, "SHA-256 mismatch"):
            load_dataset(self.root)

    def test_manifest_counts_checked(self):
        path = self.root / "manifest.json"
        data = json.loads(path.read_text())
        data["documents"] = 999
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValidationError, "row count mismatch"):
            load_dataset(self.root)

    def test_duplicate_ids_rejected_even_with_valid_hashes(self):
        records = [json.loads(line) for line in (self.root / "documents.jsonl").read_text().splitlines()]
        fixture(self.root, documents=records + [records[0]])
        with self.assertRaisesRegex(ValidationError, "duplicate doc_id"):
            load_dataset(self.root)

    def test_bad_positive_qrels_rejected(self):
        for did, message in (("missing", "unknown"), ("other-box", "another mailbox"), ("future", "unavailable")):
            with self.subTest(doc_id=did):
                fixture(self.root, qrels=[{"query_id": "q1", "doc_id": did, "relevance": 1}])
                with self.assertRaisesRegex(ValidationError, message):
                    load_dataset(self.root)

    def test_schema_and_calendar_validation(self):
        records = [json.loads(line) for line in (self.root / "documents.jsonl").read_text().splitlines()]
        records[0]["doc_dt"] = "2025-02-30"
        fixture(self.root, documents=records)
        with self.assertRaisesRegex(ValidationError, "invalid calendar date"):
            load_dataset(self.root)
        del records[0]["doc_dt"]
        fixture(self.root, documents=records)
        with self.assertRaisesRegex(ValidationError, "missing doc_dt"):
            load_dataset(self.root)


class EngineAndEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = fixture(Path(self.temp.name) / "data")
        self.dataset = load_dataset(self.root)
        self.engine = BM25Engine(tuple(self.dataset.documents.values()))

    def test_relative_and_explicit_dates(self):
        for text, expected in (("чек вчера", ["d1"]), ("чек 1 января 2025 года", ["d1"]),
                               ("чек 2025-01-01", ["d1"]), ("чек сегодня", ["d2"])):
            with self.subTest(query=text):
                request = SearchRequest(text, "a", date(2025, 1, 2))
                self.assertEqual([hit.doc_id for hit in self.engine.search(request, 10)], expected)
        self.assertEqual(target_day("письмо вчера", date(2024, 3, 1))[0], date(2024, 2, 29))
        self.assertIsNone(target_day("с 1 января 2025 по 2 января 2025", date(2025, 1, 3))[0])

    def test_no_temporal_expression_keeps_null_but_excludes_future_and_other_box(self):
        request = SearchRequest("чек", "a", date(2025, 1, 2))
        ids = [hit.doc_id for hit in self.engine.search(request, 100)]
        self.assertEqual(ids, ["d1", "d2", "unknown-date"])
        self.assertEqual(self.engine.search(SearchRequest("несуществующее", "a", date(2025, 1, 2)), 10), [])

    def test_unknown_box_and_empty_query_fail(self):
        for text, user in (("чек", "missing"), (" ", "a")):
            with self.assertRaises(ValueError):
                self.engine.search(SearchRequest(text, user, date(2025, 1, 2)), 10)

    def test_invalid_rankings_rejected(self):
        for ranking, message in ((["missing"], "unknown doc_id"), (["d1", "d1"], "duplicate"),
                                  (["other-box"], "another mailbox"), (["future"], "unavailable")):
            with self.subTest(ranking=ranking), self.assertRaisesRegex(ValidationError, message):
                validate_ranking(self.dataset, self.dataset.queries[0], ranking)

    def test_coverage_and_k_validation(self):
        for predictions in ({"q1": []}, {"q1": [], "q2": [], "extra": []}):
            with self.assertRaisesRegex(ValidationError, "coverage mismatch"):
                evaluate(self.dataset, predictions, [1])
        with self.assertRaises(ValidationError):
            evaluate(self.dataset, {"q1": [], "q2": []}, [0])

    def test_macro_metrics_and_single_relevant_subset(self):
        metrics, per_query = evaluate(self.dataset, {"q1": ["d2", "d1"], "q2": ["d1"]}, [1, 2])
        self.assertEqual(metrics["by_k"]["1"]["recall"], 0.25)
        self.assertEqual(metrics["by_k"]["1"]["mrr"], 0.5)
        self.assertEqual(metrics["by_k"]["1"]["mrr_single"], 0)
        self.assertEqual(metrics["by_k"]["2"]["mrr_single"], 0.5)
        self.assertEqual(per_query[1]["missed_doc_ids_at_max_k"], ["d2"])

    def test_failed_queries_remain_in_denominator(self):
        class BadEngine:
            def search(self, request, k):
                if "вчера" in request.query:
                    return [SearchHit("other-box", 1)]
                return [SearchHit("d1", 1), SearchHit("d2", 0.5)]
        predictions, durations, errors = run_engine(self.dataset, BadEngine(), 10)
        metrics, per_query = evaluate(self.dataset, predictions, [10], durations=durations, errors=errors)
        self.assertEqual(metrics["failed_queries"], 1)
        self.assertEqual(metrics["by_k"]["10"]["recall"], 0.5)
        self.assertIsNotNone(per_query[0]["error"])
        self.assertEqual(len(durations), 2)


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = fixture(self.root / "data")

    def command(self, *args):
        return subprocess.run([sys.executable, "-m", "mailsearch", *map(str, args)], capture_output=True, text=True)

    def test_run_rescore_compare_and_prevent_overwrite(self):
        first, rescored = self.root / "first", self.root / "rescored"
        result = self.command("run", "--dataset", self.data, "--output", first, "--ks", 1, 10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({p.name for p in first.iterdir()}, {
            "run.json", "metrics.json", "predictions.jsonl", "per_query.jsonl", "report.md"})
        metadata = json.loads((first / "run.json").read_text())
        self.assertFalse(metadata["engine_latency"]["official_server_p99_measured"])
        self.assertEqual(metadata["engine_config"]["k1"], 1.2)
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

    def test_duplicate_query_in_predictions_rejected(self):
        path = self.root / "predictions.jsonl"
        path.write_text('{"query_id":"q1","doc_ids":[]}\n' * 2)
        with self.assertRaisesRegex(ValidationError, "duplicate query_id"):
            read_predictions(path)


if __name__ == "__main__":
    unittest.main()
