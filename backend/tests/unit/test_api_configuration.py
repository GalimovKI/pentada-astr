"""Server lifecycle and boundary tests that do not require PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from pydantic import ValidationError
from mail_search.api.app import create_app
from mail_search.core.engine import LoadedEngine
from mail_search.core.settings import Settings


class ServerConfigurationTests(unittest.TestCase):
    def test_settings_and_secret_redaction(self):
        config = Settings(database_url="postgresql://user:SECRET@localhost/db")
        self.assertNotIn("SECRET", repr(config))
        with self.assertRaises(ValidationError):
            Settings(database_url="postgresql://localhost/db", search_engine_factory="bad/path")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValidationError):
                Settings.from_env()
            with TestClient(create_app()) as client:
                self.assertEqual(client.get("/health/live").status_code, 200)
                self.assertEqual(client.get("/health/ready").status_code, 503)

    def test_invalid_engine_metadata_is_not_ready(self):
        for fingerprint in (None, "", "not-a-hash", 123):
            store, db, close = Mock(), Mock(), Mock()
            store.import_fingerprint.return_value = "a" * 64
            with TestClient(create_app(Settings(database_url="postgresql://unused"),
                    database_factory=lambda _: db, store_factory=lambda _: store,
                    loader=lambda _: LoadedEngine(Mock(), fingerprint, close))) as client:
                response = client.get("/health/ready")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "engine_metadata_missing")
            close.assert_called_once()
            db.dispose.assert_called_once()

    def test_cleanup_after_close_failure(self):
        db, store = Mock(), Mock()
        store.import_fingerprint.return_value = "a" * 64
        close = Mock(side_effect=RuntimeError("close failure"))
        with self.assertRaisesRegex(RuntimeError, "close failure"):
            with TestClient(create_app(Settings(database_url="postgresql://unused"),
                    database_factory=lambda _: db, store_factory=lambda _: store,
                    loader=lambda _: LoadedEngine(Mock(), "a" * 64, close))):
                pass
        db.dispose.assert_called_once()

    def test_server_timing_includes_engine_wait(self):
        entered, release = threading.Event(), threading.Event()
        engine, db, store = Mock(), Mock(), Mock()
        store.import_fingerprint.return_value = "a" * 64
        store.list_mailboxes.return_value = ["a"]
        store.get_previews.return_value = []
        def search(request, k):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test release missing")
            return []
        engine.search.side_effect = search
        with TestClient(create_app(Settings(database_url="postgresql://unused"),
                database_factory=lambda _: db, store_factory=lambda _: store,
                loader=lambda _: LoadedEngine(engine, "a" * 64))) as client:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.post, "/api/v1/mailboxes/a/search",
                                     json={"query": "test", "query_date": "2028-09-11"})
                try:
                    self.assertTrue(entered.wait(5))
                    # Keep computation pending for a measurable interval.
                    threading.Event().wait(0.08)
                finally:
                    release.set()
                response = future.result(timeout=5)
            self.assertEqual(response.status_code, 200)
            self.assertGreaterEqual(float(response.headers["Server-Timing"].split("=")[1]), 80)
