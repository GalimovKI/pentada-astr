import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from mail_search.api.app import create_app
from mail_search.application.spelling import correct_query, spelling_hints
from mail_search.core.engine import LoadedEngine
from mail_search.core.settings import Settings


class SpellingTests(unittest.TestCase):
    def test_single_edits_across_languages_and_unicode_offsets(self):
        text = "📩 штрфа за досатвку, invocie"
        corrected, changes = correct_query(text)
        self.assertEqual(corrected, "📩 штраф за доставку, invoice")
        self.assertEqual([text[c.start:c.end] for c in changes], ["штрфа", "досатвку", "invocie"])
        self.assertEqual(correct_query("Штрфа и отпавка")[0], "Штраф и отправка")

    def test_ids_names_and_existing_words(self):
        query = "бронь, выслать Тимофею INV-штрфа-2 A45_штрфа @invoiec test@штрфа.ru https://example.org/?q=штрфа"
        self.assertEqual(correct_query(query), (query, []))

    def test_short_words_duplicates_missing_letters_and_vowels(self):
        cases = (
            ("закз, чке, срко, штрф", "заказ, чек, срок, штраф"),
            ("даставка, католог, упоковка", "доставка, каталог, упаковка"),
            ("сроок и оплта", "срок и оплата"),
            ("согласовнный график грузоперевзок", "согласованный график грузоперевозок"),
            ("delviery and reecipt", "delivery and receipt"),
        )
        for query, expected in cases:
            with self.subTest(query=query):
                corrected, changes = correct_query(query, preserve_forms=True)
                self.assertEqual(corrected, expected)
                self.assertEqual([query[c.start:c.end] for c in changes], [c.original for c in changes])
        literal = "график и шарф, от Марии, INV-закз-2, шраф@example.ru, https://example.org/даставка"
        self.assertEqual(correct_query(literal, preserve_forms=True), (literal, []))
        terms = "шаровый, подкатного, поворотник, холдере"
        self.assertEqual(correct_query(terms, preserve_forms=True), (terms, []))

    def test_typos_in_productive_forms_are_corrected_before_search(self):
        query = "закзаик и закаазики"
        corrected, changes = correct_query(query, preserve_forms=True)
        self.assertEqual(corrected, "заказик и заказики")
        self.assertEqual([c.replacement for c in changes], ["заказик", "заказики"])
        self.assertEqual(spelling_hints(query, expand_word_forms=True)["changes"], changes)
        self.assertEqual(correct_query("закзик, доствочках, товарчк", preserve_forms=True)[0],
                         "заказик, доставочках, товарчик")

    def test_prefixes_at_the_caret_do_not_affect_silent_search(self):
        query = "📩 испр в отчёте"
        hints = spelling_hints(query, cursor=6)
        self.assertEqual(hints["completions"][0].replacement, "исправить")
        self.assertTrue(all((c.start, c.end) == (2, 6) for c in hints["completions"]))
        self.assertEqual(len(hints["completions"]), 3)
        self.assertEqual(hints["changes"], [])
        self.assertEqual(correct_query("испр"), ("испр", []))
        self.assertTrue(spelling_hints("штр")["completions"])
        self.assertEqual(spelling_hints("invoi")["completions"][0].replacement, "invoice")
        for text in ("ис", "испр ", "https://site.ru/испр", "test@испр", "SKU-испр"):
            self.assertEqual(spelling_hints(text)["completions"], [], text)

    def test_http_suggestions_and_opt_in_search(self):
        store, engine = Mock(), Mock()
        store.import_fingerprint.return_value = "a" * 64
        store.list_mailboxes.return_value = ["box"]
        store.get_previews.return_value = []
        engine.search.return_value = []
        app = create_app(Settings(database_url="postgresql://unused"), database_factory=lambda _: Mock(),
                         store_factory=lambda _: store, loader=lambda _: LoadedEngine(engine, "a" * 64))
        with TestClient(app) as client:
            url = "/api/v1/mailboxes/box/search"
            body = dict(query="штрфа", query_date="2025-02-02")
            preview = client.post("/api/v1/spelling", json={"query": "штрфа"})
            self.assertEqual(preview.json()["changes"][0]["replacement"], "штраф")
            hints = client.post("/api/v1/spelling", json={"query": "испр завтра", "cursor": 4})
            self.assertEqual(hints.json()["completions"][0]["replacement"], "исправить")
            for flag, expected in (({}, "штрфа"), ({"correct_typos": True}, "штраф")):
                self.assertEqual(client.post(url, json={**body, **flag}).status_code, 200)
                self.assertEqual(engine.search.call_args.args[0].query, expected)

            for text, fixed in (("штрфаик", "штрафик"), ("оштрафвоали", "оштрафовали")):
                options = dict(query=text, expand_word_forms=True)
                preview = client.post("/api/v1/spelling", json=options).json()
                self.assertEqual(preview["changes"][0]["replacement"], fixed)
                self.assertNotIn("related", preview)
                engine.search.reset_mock()
                response = client.post(url, json={**body, **options, "correct_typos": True})
                self.assertEqual(response.status_code, 200)
                calls = [call.args[0].query for call in engine.search.call_args_list]
                self.assertEqual(calls[:2], ["штраф", fixed])
                self.assertNotIn(text, calls)
