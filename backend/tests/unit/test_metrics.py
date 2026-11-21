import math
import unittest

from mail_search.evaluation.metrics import metrics_at_k
from mail_search.benchmarks.latency import percentile


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
