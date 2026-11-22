import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import Mock

from fastapi.testclient import TestClient
from mail_search.api.app import create_app
from mail_search.application.derivational_stemmer import fit_suffix_stemmer
from mail_search.application.mail import MailService
from mail_search.application.spelling import correct_query, spelling_hints
from mail_search.application.word_forms import russian_morphology, search_queries
from mail_search.core.engine import LoadedEngine
from mail_search.core.settings import Settings
from mail_search.domain.models import Document
from mail_search.search.bm25 import BM25Engine


class WordFormTests(unittest.TestCase):
    def test_held_out_word_requires_learned_examples(self):
        morphology = russian_morphology()
        self.assertIsNone(fit_suffix_stemmer([]).predict("штрафик", morphology))
        examples = [("домик", "дом"), ("столик", "стол"), ("мостик", "мост"), ("носик", "нос")]
        model = fit_suffix_stemmer(examples)
        self.assertEqual(model.predict("штрафик", morphology), "штраф")
        self.assertEqual(model.predict("штрафиками", morphology), "штраф")
        self.assertIsNone(model.predict("график", morphology))

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

    def test_unlisted_colloquialisms_after_spelling_correction(self):
        for surface, base in (("терминальчик", "терминал"), ("терминальчиками", "терминал"),
                              ("контрактец", "контракт")):
            with self.subTest(surface=surface):
                self.assertEqual(search_queries(surface)[:2], (base, surface))
                self.assertEqual(correct_query(surface, preserve_forms=True), (surface, []))
        corrected, _ = correct_query("про штрфаик и терминальчики", preserve_forms=True)
        self.assertEqual(corrected, "про штрафик и терминальчики")
        self.assertEqual(search_queries(corrected)[0], "про штраф и терминал")

    def test_context_disambiguates_inflected_search_words(self):
        cases = {"новые посылочки приехали": "новый посылка приехать",
                 "доставили новые посылочки": "доставить новый посылка",
                 "срочных заказов": "срочный заказ",
                 "из стали": "из сталь", "они стали работать": "они стать работать"}
        for query, canonical in cases.items():
            with self.subTest(query=query):
                variants = search_queries(query)
                self.assertEqual(variants[0], canonical)
                self.assertIn(query, variants)
        for word, primary, other in (("стали", "стать", "сталь"), ("графики", "графика", "график")):
            with self.subTest(word=word):
                alternatives = search_queries(word)
                self.assertEqual(alternatives[0], primary)
                self.assertIn(other, alternatives)
                self.assertIn(word, alternatives)
        self.assertEqual(search_queries("из, стали")[0], "из, стать")

    def test_ambiguous_names_dates_and_identifiers(self):
        for word in ("график", "ручка", "заказчик", "переводчик",
                     "поводок", "дворник", "кузнец", "огурец", "Марина", "INV-заказик", "заказик@почта.рф"):
            self.assertEqual(search_queries(word), (word,), word)
        self.assertEqual(search_queries("гвоздик")[0], "гвоздик")
        queries = search_queries("найди заказики от Марии за 5 декабря 2028 года")
        self.assertIn("найти заказ от Марии за 5 декабря 2028 года", queries)
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
        for word, lemma, related in (("оштрафовали", "оштрафовать", "штраф"),
                                     ("доставили", "доставить", "доставка"),
                                     ("оплатили", "оплатить", "оплата")):
            with self.subTest(word=word):
                alternatives = search_queries(word)
                self.assertEqual(alternatives[:2], (lemma, word))
                self.assertIn(related, alternatives)
        for word in ("штрафиком", "штрафчиками", "оштрафуют", "оштрафована"):
            self.assertIn("штраф", search_queries(word))
            self.assertEqual(correct_query(word, preserve_forms=True)[0], word)
        self.assertIn("оплата за штраф", search_queries("оплата за штрафик"))
        payments = search_queries("об отклонённых платежах")
        self.assertIn("оплата", payments[0])
        self.assertTrue(any("платёж" in variant for variant in payments))
        self.assertIn("открытка", search_queries("открытками"))
        for text in ("марии", "переводчик", "SKU-штрафик", "штрафик@example.ru",
                     "https://банк.рф/штрафик", "ШТРАФ", "invoices"):
            self.assertEqual(search_queries(text), (text,), text)
        hints = spelling_hints("про штрафик", expand_word_forms=True)
        self.assertNotIn("related", hints)
        self.assertFalse(hints["changes"])
        self.assertNotIn("related", spelling_hints("про штрафик"))
        self.assertEqual(spelling_hints("штрафик ", expand_word_forms=True)["completions"], [])

    def test_http_retrieval_with_literal_bm25(self):
        today = date(2028, 3, 1)
        documents = [
            Document("a", "one", "штраф", today),
            Document("b", "one", "штрафик", today),
            Document("c", "one", "оштрафовали", today),
            Document("verb", "one", "оштрафовать", today),
            Document("later", "one", "штрафик", date(2028, 3, 2)),
            Document("elsewhere", "two", "штраф", today),
        ]
        engine = BM25Engine(tuple(documents), stemming=False)
        store = Mock()
        store.list_mailboxes.return_value = ["one", "two"]
        store.import_fingerprint.return_value = "a" * 64
        by_id = {d.doc_id: d for d in documents}
        store.get_messages.side_effect = lambda user, ids, query_date: [by_id[i] for i in ids]
        app = create_app(Settings(database_url="postgresql://unused"), database_factory=lambda _: Mock(),
                         store_factory=lambda _: store, loader=lambda _: LoadedEngine(engine, "a" * 64))
        with TestClient(app) as client:
            for query in ("штраф", "штрафик", "оштрафовали", "штрафчиками", "штрфаик"):
                with self.subTest(query=query):
                    response = client.post("/api/v1/mailboxes/one/search?explain=true", json={
                        "query": query, "query_date": today.isoformat(),
                        "correct_typos": True, "expand_word_forms": True,
                    })
                    self.assertEqual(response.status_code, 200)
                    hits = response.json()["items"]
                    expected = {"a", "b", "c"}
                    if query == "оштрафовали":
                        self.assertEqual(hits[0]["doc_id"], "verb")
                        expected.add("verb")
                    else:
                        self.assertEqual(hits[0]["doc_id"], "a")
                    self.assertEqual({hit["doc_id"] for hit in hits}, expected)
                    self.assertTrue(all(hit["passage"] and hit["score"] > 0 for hit in hits))
