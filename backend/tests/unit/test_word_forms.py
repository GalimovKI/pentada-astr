import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import Mock

from mail_search.application.mail import MailService
from mail_search.application.spelling import correct_query, spelling_hints
from mail_search.application.word_forms import related_queries
from mail_search.core.engine import LoadedEngine
from mail_search.domain.models import Document, SearchHit
from mail_search.search.bm25 import BM25Engine


class WordFormTests(unittest.TestCase):
    def test_morphology_and_structured_terms(self):
        for word in ("штрафиком", "штрафчиками", "оштрафуют", "оштрафована"):
            self.assertIn("штраф", related_queries(word))
            self.assertEqual(correct_query(word, preserve_forms=True)[0], word)
        self.assertIn("оплата за штраф", related_queries("оплата за штрафик"))
        self.assertIn("открытка", related_queries("открытками"))
        for text in ("стали", "марии", "переводчик", "SKU-штрафик", "штрафик@example.ru",
                     "https://банк.рф/штрафик", "ШТРАФ", "invoices"):
            self.assertEqual(related_queries(text), (), text)
        hints = spelling_hints("про штрафик", expand_word_forms=True)
        self.assertEqual(hints["related"][0].replacement, "штраф")
        self.assertFalse(hints["changes"])
        self.assertNotIn("related", spelling_hints("про штрафик"))
        self.assertEqual(spelling_hints("штрафик ", expand_word_forms=True)["related"], [])

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
                result = service.search("one", query, today, 1, explain=True,
                                        relevance_threshold=1.0, alternatives=related_queries(query))
                self.assertEqual(result["total"], 3)
                self.assertEqual(result["items"][0]["doc_id"], doc.doc_id)
                self.assertEqual({h["doc_id"] for h in result["items"]}, {"a", "b", "c"})
                self.assertTrue(all(h["passage"] and h["score"] == 1.0 for h in result["items"]))

    def test_paginated_dense_union_is_filtered_sorted_then_sliced(self):
        engine, store = Mock(), Mock()
        lists = {"штраф": [SearchHit("x", .85), SearchHit("y", .7)],
                 "оштрафовали": [SearchHit("z", .9), SearchHit("x", .8)]}
        engine.relevance_scores.side_effect = lambda request: lists[request.query]
        store.import_fingerprint.return_value = "a" * 64
        store.list_mailboxes.return_value = ["one"]
        store.get_previews.side_effect = lambda user, ids, query_date: [Mock(doc_id=i) for i in ids]
        with ThreadPoolExecutor(max_workers=1) as executor:
            service = MailService(store, LoadedEngine(engine, "a" * 64), executor)
            page = service.search("one", "штраф", date(2028, 3, 1), 1, min_similarity=.8,
                                  offset=1, alternatives=("оштрафовали",))
            self.assertEqual(page["total"], 2)
            self.assertEqual([h["doc_id"] for h in page["items"]], ["x"])
