"""HTTP against isolated PostgreSQL databases, using controlled and real engines."""
from datetime import date
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from fastapi.testclient import TestClient
from sqlalchemy import event, update, delete, select
from sqlalchemy.exc import OperationalError
from mail_search.api.app import create_app
from mail_search.core.engine import LoadedEngine, load_bm25
from mail_search.core.settings import Settings
from mail_search.domain.models import SearchHit, SearchRequest
from mail_search.storage.importer import import_corpus
from mail_search.storage.repository import MailStore
from mail_search.storage.schema import corpus_import
from tests.fixtures.postgres import PostgreSQLTestCase
from tests.fixtures.dataset import fixture


class ApiTests(PostgreSQLTestCase):
    def client(self, hits=None, loader=None, store_factory=MailStore):
        imported = import_corpus(self.engine, self.path)
        self.fake = Mock()
        self.fake.search.return_value = hits if hits is not None else [SearchHit("d2", 2), SearchHit("d1", 1)]
        self.close = Mock()
        self.loader = loader or Mock(return_value=LoadedEngine(self.fake, imported["fingerprint"], self.close))
        settings = Settings(database_url="postgresql://unused", search_dataset=self.path)
        return TestClient(create_app(settings, loader=self.loader,
                          database_factory=lambda _: self.engine, store_factory=store_factory))

    def search(self, client, **changes):
        return client.post("/api/v1/mailboxes/a/search", json={
            **dict(query="чек", query_date="2025-01-02", limit=3), **changes})

    def test_http_flow(self):
        with self.client() as c:
            self.assertEqual(c.get("/health/live").json(), {"status": "live"})
            self.assertEqual(c.get("/health/ready").status_code, 200)
            self.assertEqual(c.get("/api/v1/mailboxes").json(), {"items": ["a", "b"]})
            path = "/api/v1/mailboxes/a/messages"
            seen, cursor = [], None
            while True:
                params = dict(query_date="2025-01-02", limit=1)
                if cursor:
                    params["cursor"] = cursor
                response = c.get(path, params=params)
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                seen += [x["doc_id"] for x in data["items"]]
                self.assertNotIn("doc", data["items"][0])
                cursor = data["next_cursor"]
                if cursor is None:
                    break
            self.assertEqual(seen, ["d2", "d1", "unknown-date"])
            self.assertIsNone(data["items"][0]["doc_dt"])
            for did in ("future", "other-box", "missing"):
                response = c.get(f"{path}/{did}", params={"query_date": "2025-01-02"})
                self.assertEqual((response.status_code, response.json()), (404, {"error": {"code": "message_not_found"}}))
            response = c.get(f"{path}/d1", params={"query_date": "2025-01-02"})
            self.assertEqual(response.json()["item"]["doc"], self.store.get_message("a", "d1").doc)
            for suffix in ("messages?query_date=2025-01-02", "messages/d1?query_date=2025-01-02"):
                self.assertEqual(c.get("/api/v1/mailboxes/missing/" + suffix).status_code, 404)
            result = self.search(c)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual([h["doc_id"] for h in result.json()["items"]], ["d2", "d1"])
            self.assertIn("Server-Timing", result.headers)
            self.fake.search.assert_called_once_with(SearchRequest("чек", "a", date(2025, 1, 2)), 3)
            self.assertEqual(c.post("/api/v1/mailboxes/missing/search", json={"query": "чек", "query_date": "2025-01-02"}).status_code, 404)
        self.loader.assert_called_once()
        self.close.assert_called_once()

    def test_validation(self):
        with self.client() as c:
            for change in ({"query": ""}, {"query": " \n"}, {"query": "x" * 4001},
                           {"query": True}, {"limit": True}, {"limit": "2"}, {"limit": 1.2},
                           {"limit": 0}, {"limit": 101}, {"query_date": "2025-1-02"},
                           {"query_date": "2025-02-30"}, {"query_date": 123},
                           {"query_date": "2025-01-02T00:00:00"}, {"unexpected": "secret"}):
                r = self.search(c, **change)
                self.assertEqual(r.status_code, 422, (change, r.text))
                self.assertEqual(r.json(), {"error": {"code": "validation_error"}})
            for params in ({}, {"query_date": "2025-01-02", "limit": "true"},
                           {"query_date": "2025-01-02", "limit": "1.0"},
                           {"query_date": "2025-01-02", "cursor": "!!"},
                           {"query_date": "2025-01-02", "cursor": "a" * 4097}):
                self.assertEqual(c.get("/api/v1/mailboxes/a/messages", params=params).status_code, 422)
            self.assertEqual(self.search(c, query_date="2028-09-11").status_code, 200)
            self.fake.search.assert_called_once()

    def test_cursor_context(self):
        with self.client() as c:
            cursor = c.get("/api/v1/mailboxes/a/messages?query_date=2025-01-02&limit=1").json()["next_cursor"]
            for user, day in (("b", "2025-01-02"), ("a", "2025-01-03")):
                self.assertEqual(c.get(f"/api/v1/mailboxes/{user}/messages", params={"query_date": day, "cursor": cursor}).status_code, 422)

    def test_contract_and_failure(self):
        cases = [[SearchHit("d1", 1)] * 2, [SearchHit("d1", float("nan"))],
                 [SearchHit("d1", float("inf"))], [SearchHit("future", 1)],
                 [SearchHit("other-box", 1)], [SearchHit("missing", 1)],
                 [SearchHit("d1", 1)] * 4, [SearchHit("d1", True)], [object()]]
        with self.client() as c:
            for hits in cases:
                self.fake.search.return_value = hits
                response = self.search(c)
                self.assertEqual(response.status_code, 500, response.text)
                self.assertEqual(response.json()["error"]["code"], "engine_contract_violation")
            self.fake.search.side_effect = RuntimeError("SECRET password query text")
            response = self.search(c)
            self.assertEqual(response.json(), {"error": {"code": "engine_failure"}})
            self.fake.search.side_effect = None
            self.fake.search.return_value = []
            self.assertEqual(self.search(c).json(), {"items": []})

    def test_db_failure_and_fingerprints(self):
        with self.client() as c:
            with self.engine.begin() as conn:
                conn.execute(update(corpus_import).values(fingerprint="different"))
            self.assertEqual(c.get("/health/ready").status_code, 503)
            self.assertEqual(self.search(c).json()["error"]["code"], "dataset_mismatch")
            with self.engine.begin() as conn:
                saved = dict(conn.execute(select(corpus_import)).mappings().one())
                conn.execute(delete(corpus_import))
            self.assertEqual(self.search(c).json()["error"]["code"], "import_metadata_missing")
            self.assertEqual(c.get("/health/live").status_code, 200)
            with self.engine.begin() as conn:
                saved["fingerprint"] = self.loader.return_value.fingerprint
                conn.execute(corpus_import.insert().values(**saved))
        store = Mock()
        store.import_fingerprint.side_effect = OperationalError("SECRET SQL", {}, Exception("SECRET"))
        with self.client(store_factory=lambda _: store) as c:
            response = c.get("/health/ready")
            self.assertEqual(response.json(), {"error": {"code": "database_unavailable"}})
            self.assertEqual(response.status_code, 503)

    def test_loader_failure(self):
        with self.client(loader=Mock(side_effect=RuntimeError("SECRET PATH"))) as c:
            self.assertEqual(c.get("/health/live").status_code, 200)
            self.assertEqual(c.get("/health/ready").status_code, 503)
            self.assertEqual(self.search(c).status_code, 503)

    def test_real_bm25_and_batch_previews(self):
        with self.client(loader=load_bm25) as c:
            statements = []
            def record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)
            event.listen(self.engine, "before_cursor_execute", record)
            try:
                response = self.search(c)
            finally:
                event.remove(self.engine, "before_cursor_execute", record)
            self.assertEqual(response.status_code, 200, response.text)
            actual = response.json()["items"]
            expected = load_bm25(Settings(database_url="postgresql://unused", search_dataset=self.path)).engine.search(SearchRequest("чек", "a", date(2025, 1, 2)), 3)
            self.assertEqual([x["doc_id"] for x in actual], [x.doc_id for x in expected])
            reads = [s for s in statements if "FROM messages" in s]
            self.assertEqual(len(reads), 1)
            self.assertIn("left(messages.doc", reads[0])
            self.assertNotIn("doc", actual[0])

    def test_engine_thread_affinity_and_serialization(self):
        threads = []
        def loader(settings):
            threads.append(threading.get_ident())
            class Engine:
                def search(self, request, k):
                    threads.append(threading.get_ident())
                    return []
            return LoadedEngine(Engine(), self.store.import_fingerprint(), lambda: threads.append(threading.get_ident()))
        with self.client(loader=loader) as c:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: self.search(c).status_code, range(8)))
            self.assertEqual(results, [200] * 8)
        self.assertEqual(len(threads), 10)
        self.assertEqual(len(set(threads)), 1)

    def test_long_text_ties_and_multiple_nulls(self):
        body = "  <html>Текст\r\n'цитата'\t😀" + "я" * 600 + "\n "
        fixture(self.path, documents=[dict(doc_id=did, synthetic_user=user, doc=body, doc_dt=dt)
            for did, user, dt in (("d1", "a", "2025-01-01"), ("d2", "a", "2025-01-02"),
                ("A", "a", "2025-01-02"), ("n1", "a", None), ("n2", "a", None),
                ("foreign", "b", None), ("future", "a", "2025-01-03"))])
        with self.client(hits=[SearchHit("n2", 2), SearchHit("A", 1)]) as c:
            path = "/api/v1/mailboxes/a/messages"
            seen, cursor = [], None
            while True:
                params = dict(query_date="2025-01-02", limit=1)
                if cursor:
                    params["cursor"] = cursor
                data = c.get(path, params=params).json()
                self.assertEqual(data["items"][0]["snippet"], body[:200])
                seen.append(data["items"][0]["doc_id"])
                cursor = data["next_cursor"]
                if cursor is None:
                    break
            self.assertEqual(seen, ["A", "d2", "d1", "n1", "n2"])
            self.assertEqual(c.get(path + "/n1?query_date=2025-01-02").json()["item"]["doc"], body)
            result = self.search(c).json()["items"]
            self.assertEqual([x["doc_id"] for x in result], ["n2", "A"])
            self.assertIsNone(result[0]["doc_dt"])
            self.assertTrue(all(x["snippet"] == body[:200] and "doc" not in x for x in result))

    def test_missing_metadata_at_start_and_cleanup(self):
        import_corpus(self.engine, self.path)
        with self.engine.begin() as conn:
            conn.execute(delete(corpus_import))
        closed = Mock()
        db = Mock(wraps=self.engine)
        config = Settings(database_url="postgresql://unused")
        with TestClient(create_app(config, loader=lambda _: LoadedEngine(Mock(), "a" * 64, closed),
                                  database_factory=lambda _: db)) as c:
            self.assertEqual(c.get("/health/ready").json()["error"]["code"], "import_metadata_missing")
            self.assertEqual(c.get("/api/v1/mailboxes").status_code, 503)
        closed.assert_called_once()
        db.dispose.assert_called_once()

    def test_server_factory_setting(self):
        # Actual import path loading, separate from injected loader tests.
        imported = import_corpus(self.engine, self.path)
        settings = Settings(database_url="postgresql://unused", search_dataset=self.path,
                            search_engine_factory="mail_search.core.engine:load_bm25")
        with TestClient(create_app(settings, database_factory=lambda _: self.engine)) as c:
            self.assertEqual(self.search(c).status_code, 200)
            spec = c.get("/openapi.json").json()
            self.assertIn("/api/v1/mailboxes/{synthetic_user}/search", spec["paths"])
            self.assertIn("ErrorResponse", spec["components"]["schemas"])
