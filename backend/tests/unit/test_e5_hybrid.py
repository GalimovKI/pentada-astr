from datetime import date
from importlib.util import find_spec
from unittest import TestCase, skipUnless
from unittest.mock import Mock

from mail_search.domain.models import Document, SearchHit, SearchRequest
from mail_search.search.e5_hybrid import E5HybridEngine


class HybridTests(TestCase):
    def setUp(self):
        self.lexical, self.dense = Mock(), Mock()
        self.lexical.search.return_value = [SearchHit("b", 8), SearchHit("a", 6)]
        self.lexical.relevance_scores.return_value = [SearchHit("b", 1), SearchHit("a", .75)]
        self.request = SearchRequest("счёт", "mine", date(2029, 1, 2))
        self.dense.search_page.return_value = ([SearchHit("c", .99), SearchHit("a", .9)], 2)

    def engine(self, strategy):
        return E5HybridEngine(self.lexical, self.dense, {
            "strategy": strategy, "candidate_depth": 2, "rrf_constant": 10, "lexical_weight": .75,
        })

    def test_rrf_combines_shared_evidence_and_keeps_fixed_candidate_depth(self):
        engine = self.engine("rrf")
        hits = engine.search(self.request, 100)
        self.assertEqual([h.doc_id for h in hits], ["a", "b", "c"])
        self.assertAlmostEqual(hits[0].score, 11/12)
        self.assertEqual(hits[:1], engine.search(self.request, 1))
        self.lexical.search.assert_called_with(self.request, 2)
        self.dense.search_page.assert_called_with(self.request, 2, receipt_date=None)

    def test_dense_first_preserves_candidate_pool_and_reorders_lexical_match(self):
        hits = self.engine("dense_first").search(self.request, 100)
        self.assertEqual([h.doc_id for h in hits], ["a", "c"])
        self.assertAlmostEqual(hits[0].score, .75 + .25 * .9)
        self.assertAlmostEqual(hits[1].score, .25 * .99)

    @skipUnless(find_spec("numpy"), "requires dense retrieval dependencies")
    def test_cascades_enforce_box_availability_receipt_day_and_pool(self):
        import numpy as np
        from mail_search.search.e5 import E5Engine
        from mail_search.search.event_aware import create_engine

        day = date(2029, 1, 1)
        docs = [Document("a", "mine", "счёт", day), Document("b", "mine", "счёт завтра", date(2029, 1, 2)),
                Document("c", "other", "счёт", day), Document("d", "mine", "счёт", date(2029, 1, 3)),
                Document("e", "mine", "счёт", None)]
        encoder = Mock()
        encoder.encode.return_value = np.array([[1.0]])
        self.dense = E5Engine(docs, np.array([[.6], [.7], [.9], [1], [.8]]), encoder)
        self.lexical = create_engine(tuple(docs), {})
        request = SearchRequest("счёт, полученный вчера", "mine", date(2029, 1, 2))
        for method in ("rrf", "dense_first", "lexical_first"):
            with self.subTest(method=method):
                hits = self.engine(method).search(request, 100)
                self.assertEqual([h.doc_id for h in hits], ["a"])
        # An undated document can surface if no receipt day is requested.
        scores, _ = self.dense.search_page(self.request, 10, candidate_ids=["a", "c", "d", "e"])
        self.assertEqual([h.doc_id for h in scores], ["e", "a"])
