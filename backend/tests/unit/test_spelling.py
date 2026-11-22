import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from mail_search.api.app import create_app
from mail_search.application.spelling import correct_query
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
            self.assertEqual(client.post("/api/v1/spelling", json={"query": "штрфа"}).status_code, 404)
            self.assertEqual(client.post(url, json={**body, "correct_typos": True}).status_code, 422)
            app.state.evaluations = Mock()
            preview = client.post("/api/v1/spelling", json={"query": "штрфа"})
            self.assertEqual(preview.json()["changes"][0]["replacement"], "штраф")
            for flag, expected in (({}, "штрфа"), ({"correct_typos": True}, "штраф")):
                self.assertEqual(client.post(url, json={**body, **flag}).status_code, 200)
                self.assertEqual(engine.search.call_args.args[0].query, expected)
