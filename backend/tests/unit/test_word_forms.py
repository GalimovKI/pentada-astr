import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import Mock

from mail_search.application.mail import MailService
from mail_search.application.spelling import correct_query, spelling_hints
from mail_search.application.word_forms import search_queries
from mail_search.core.engine import LoadedEngine
from mail_search.domain.models import Document
from mail_search.search.bm25 import BM25Engine


class WordFormTests(unittest.TestCase):
    def test_dictionary_and_productive_diminutives_in_search(self):
        cases = {"заказик": "заказ", "заказиками": "заказ", "Счётиком": "Счёт",
                 "авансиках": "аванс", "складику": "склад", "заявочку": "заявка",
                 "письмецом": "письмо", "билетиков": "билет", "пакетиками": "пакет",
                 "контейнерчиками": "контейнер", "доставочкой": "доставка",
                 "документиками": "документ", "посылочках": "посылка"}
        for surface, base in cases.items():
            with self.subTest(surface=surface):
                self.assertEqual(search_queries(surface)[:2], (base, surface))
                self.assertEqual(correct_query(surface, preserve_forms=True), (surface, []))
        self.assertEqual(search_queries("про заказик и билетики")[0], "про заказ и билет")
        self.assertIn("срочный заказ", search_queries("срочных заказов"))

    def test_ambiguous_names_dates_and_identifiers(self):
        for word in ("график", "ручка", "заказчик", "переводчик", "гвоздик",
                     "поводок", "дворник", "Марина", "INV-заказик", "заказик@почта.рф"):
            self.assertEqual(search_queries(word), (word,), word)
        queries = search_queries("найди заказики от Марии за 5 декабря 2028 года")
        self.assertIn("найди заказ от Марии за 5 декабря 2028 года", queries)
        self.assertTrue(all("от Марии за 5 декабря 2028 года" in q for q in queries))

    def test_fallback_keeps_the_receipt_date(self):
        store, engine = Mock(), Mock()
        store.list_mailboxes.return_value = ["one"]
        store.import_fingerprint.return_value = "a" * 64
        store.get_previews.return_value = []
        engine.config = {}
        engine.search.return_value = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            service = MailService(store, LoadedEngine(engine, "a" * 64), executor)
            query = "пришли 5 декабря 2028 года заказы"
            alternatives = ("прийти 5 декабря 2028 года заказ", "пришли 5 декабря 2028 года заказ")
            service.search("one", query, date(2028, 12, 10), 10, alternatives=alternatives)
            self.assertEqual([call.args[0].query for call in engine.search.call_args_list],
                             [query, alternatives[1]])

    def test_morphology_and_structured_terms(self):
        for word in ("штрафиком", "штрафчиками", "оштрафуют", "оштрафована"):
            self.assertIn("штраф", search_queries(word))
            self.assertEqual(correct_query(word, preserve_forms=True)[0], word)
        self.assertIn("оплата за штраф", search_queries("оплата за штрафик"))
        self.assertIn("открытка", search_queries("открытками"))
        for text in ("стали", "марии", "переводчик", "SKU-штрафик", "штрафик@example.ru",
                     "https://банк.рф/штрафик", "ШТРАФ", "invoices"):
            self.assertEqual(search_queries(text), (text,), text)
        hints = spelling_hints("про штрафик", expand_word_forms=True)
        self.assertNotIn("related", hints)
        self.assertFalse(hints["changes"])
        self.assertNotIn("related", spelling_hints("про штрафик"))
        self.assertEqual(spelling_hints("штрафик ", expand_word_forms=True)["completions"], [])

    def test_bidirectional_retrieval_with_literal_bm25(self):
        today = date(2028, 3, 1)
        documents = [
            Document("a", "one", "штраф", today),
            Document("b", "one", "штрафик", today),
            Document("c", "one", "оштрафовали", today),
            Document("later", "one", "штрафик", date(2028, 3, 2)),
            Document("elsewhere", "two", "штраф", today),
        ]
        engine = BM25Engine(tuple(documents), stemming=False)
        store = Mock()
        store.list_mailboxes.return_value = ["one", "two"]
        store.import_fingerprint.return_value = "a" * 64
        by_id = {d.doc_id: d for d in documents}
        store.get_messages.side_effect = lambda user, ids, query_date: [by_id[i] for i in ids]
        with ThreadPoolExecutor(max_workers=1) as executor:
            service = MailService(store, LoadedEngine(engine, "a" * 64), executor)
            for doc in documents[:3]:
                query = doc.doc
                primary, *secondary = search_queries(query)
                result = service.search("one", primary, today, 10, explain=True, alternatives=secondary)
                self.assertEqual(result["items"][0]["doc_id"], "a")
                self.assertEqual({h["doc_id"] for h in result["items"]}, {"a", "b", "c"})
                self.assertTrue(all(h["passage"] and h["score"] > 0 for h in result["items"]))
