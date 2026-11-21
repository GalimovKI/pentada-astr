import tempfile
import unittest
from datetime import date
from pathlib import Path

from mail_search.core.errors import ValidationError
from mail_search.domain.models import SearchHit, SearchRequest
from mail_search.ingestion.dataset import load_dataset
from mail_search.search.bm25 import BM25Engine
from mail_search.search.dates import target_day
from mail_search.evaluation.runner import evaluate, run_engine, validate_ranking
from tests.fixtures.dataset import fixture


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
