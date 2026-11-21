import unittest
from datetime import date
from time import monotonic
from unittest.mock import patch

from mail_search.domain.models import Document, SearchRequest
from mail_search.search.bm25 import BM25Engine
from mail_search.search.fuzzy import create_engine


class FuzzySearchTests(unittest.TestCase):
    def setUp(self):
        self.anchor = date(2027, 3, 8)
        yesterday = date(2027, 3, 7)
        self.documents = (
            Document("a", "box", "КонтейнерSYN-1 выгружен. Накладная А12.", yesterday),
            Document("b", "box", "Контейнер на досмотре. Накладная А13.", yesterday),
            Document("c", "box", "Выгрузка контейнера.", self.anchor),
            Document("d", "other", "Выгрузка контейнера.", yesterday),
            Document("e", "box", "Выгрузка контейнера.", None),
            Document("f", "box", "Выгрузка контейнера.", date(2027, 3, 9)),
        )
        self.engine = create_engine(self.documents, {})

    def search(self, text):
        return self.engine.search(SearchRequest(text, "box", self.anchor), 10)

    def test_partial_word_match_ranks_relevant_action_within_receipt_day(self):
        hits = self.search("Покажи уведомления о выгрузке контейнера, полученные вчера")
        self.assertEqual([hit.doc_id for hit in hits], ["a", "b"])
        self.assertGreater(hits[0].score, hits[1].score)

    def test_dated_query_retains_exact_mixed_identifier(self):
        hits = self.search("А12 вчера")
        self.assertEqual(hits[0].doc_id, "a")
        self.assertGreater(hits[0].score, 0)
        self.assertEqual(hits[1].score, 0)
        self.assertEqual(self.search("А14 вчера"), [])

    def test_query_without_receipt_day_uses_stemmed_bm25(self):
        request = SearchRequest("выгрузка контейнера", "box", self.anchor)
        base = BM25Engine(self.documents, stemming=True, date_mode="contextual")
        self.assertEqual(self.engine.search(request, 10), base.search(request, 10))

    def test_date_only_and_future_dates(self):
        self.assertEqual([hit.doc_id for hit in self.search("вчера")], ["a", "b"])
        self.assertEqual(self.search("письма за 2027-03-09"), [])

    def test_expired_caller_budget_fails_explicitly(self):
        request = SearchRequest("выгрузка вчера", "box", self.anchor)
        with self.assertRaises(TimeoutError):
            self.engine.search(request, 10, deadline=monotonic() - 1)

    def test_no_date_bm25_uses_the_same_budget(self):
        # Let the initial checks finish, then expire the budget inside BM25.
        clock = iter((10.0, 10.0, 11.0))
        with patch("mail_search.search.fuzzy.monotonic", return_value=10.0), \
                patch("mail_search.search.deadline.monotonic", side_effect=lambda: next(clock)):
            with self.assertRaises(TimeoutError):
                self.search("выгрузка контейнера")
