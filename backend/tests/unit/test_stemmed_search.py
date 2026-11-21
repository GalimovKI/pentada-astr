import unittest
from datetime import date

from mail_search.domain.models import Document, SearchRequest
from mail_search.indexing.text import tokenize_stemmed
from mail_search.search.bm25 import BM25Engine
from mail_search.search.dates import receipt_day


class StemmedSearchTests(unittest.TestCase):
    def setUp(self):
        self.as_of = date(2028, 12, 16)
        self.engine = BM25Engine((
            Document("orders", "box-a", "Заявка с заказами ABC123", date(2028, 12, 15)),
            Document("later", "box-a", "Заявка с заказами ABC123", date(2028, 12, 17)),
            Document("foreign", "box-b", "Заявка с заказами ABC123", date(2028, 12, 15)),
            Document("meeting", "box-a", "Встреча назначена на 15 декабря 2028 года", date(2028, 12, 13)),
            Document("undated", "box-a", "Заявка по заказам", None),
        ), stemming=True, date_mode="contextual")

    def ids(self, query):
        return [hit.doc_id for hit in self.engine.search(SearchRequest(query, "box-a", self.as_of), 10)]

    def test_morphology_and_filtering(self):
        self.assertEqual(self.ids("заказ, полученный 15 декабря 2028 года"), ["orders"])
        self.assertEqual(set(self.ids("заказ")), {"orders", "undated"})
        self.assertEqual(tokenize_stemmed("Заказами ABC123 АБВ123"), ["заказ", "abc123", "абв123"])

    def test_event_date_is_searchable_even_for_message_received_earlier(self):
        self.assertEqual(self.ids("встреча на 15 декабря 2028 года")[0], "meeting")
        day, text = receipt_day("вчерашнее письмо о встрече на 20 декабря 2028 года", self.as_of)
        self.assertEqual(day, date(2028, 12, 15))
        self.assertIn("20 декабря 2028 года", text)

    def test_date_only_and_future(self):
        self.assertEqual(self.ids("вчера"), ["orders"])
        self.assertEqual(self.ids("заказ, полученный 17.12.2028"), [])

    def test_invalid_and_ambiguous_dates_do_not_apply_a_filter(self):
        for query in ("заказ, полученный 31 февраля 2028 года",
                      "заказ, полученный 13 декабря 2028 года по 15 декабря 2028 года",
                      "получено вчера или получено сегодня"):
            with self.subTest(query=query):
                self.assertEqual(receipt_day(query, self.as_of), (None, query))
