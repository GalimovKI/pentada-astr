"""Real PostgreSQL only; creates and drops only randomly named test databases."""
import os
from pathlib import Path
import tempfile
import unittest
from datetime import date
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import DBAPIError

from mail_search.core.errors import ValidationError
from mail_search.storage.database import database_engine
from mail_search.storage.importer import import_corpus
from mail_search.storage.repository import MailStore, UnknownMailbox
from mail_search.storage.schema import corpus_import, mailboxes, messages
from tests.fixtures.dataset import fixture


@unittest.skipUnless(os.environ.get("TEST_DATABASE_ADMIN_URL"),
                     "Set TEST_DATABASE_ADMIN_URL (PostgreSQL role with CREATEDB)")
class StorageTests(unittest.TestCase):
    def setUp(self):
        self.admin = database_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
        self.addCleanup(self.admin.dispose)
        self.name = "mailsearch_test_" + uuid4().hex
        with self.admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'CREATE DATABASE "{self.name}" TEMPLATE template0'))
        self.addCleanup(self.drop_database)
        self.engine = database_engine(self.admin.url.set(database=self.name))
        self.addCleanup(self.engine.dispose)
        self.config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        with self.engine.begin() as conn:
            self.config.attributes["connection"] = conn
            command.upgrade(self.config, "head")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = fixture(Path(self.temp.name))
        self.store = MailStore(self.engine)

    def drop_database(self):
        # Name is locally generated, never derived from either configured URL.
        with self.admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f'DROP DATABASE "{self.name}" WITH (FORCE)'))

    def test_migration_and_repeat_import(self):
        self.assertEqual(set(inspect(self.engine).get_table_names()),
                         {"alembic_version", "mailboxes", "messages", "corpus_import"})
        first = import_corpus(self.engine, self.path, batch_size=2)
        second = import_corpus(self.engine, self.path)
        self.assertEqual(first["status"], "imported")
        self.assertEqual(second, dict(first, status="already_imported"))
        self.assertEqual((first["mailboxes"], first["messages"], first["unknown_dates"]), (2, 5, 1))
        with self.engine.connect() as conn:
            saved = conn.execute(select(corpus_import)).mappings().one()
            self.assertEqual(saved["fingerprint"], first["fingerprint"])
            self.assertIsNotNone(saved["imported_at"].tzinfo)
        with self.engine.begin() as conn:
            self.config.attributes["connection"] = conn
            command.upgrade(self.config, "head")
            command.check(self.config)

    def test_scope_dates_and_batch_order(self):
        import_corpus(self.engine, self.path)
        self.assertEqual(self.store.list_mailboxes(), ["a", "b"])
        today = date(2025, 1, 2)
        ids = ["unknown-date", "d2", "other-box", "missing", "future", "d1", "d2"]
        result = self.store.get_messages("a", ids, query_date=today)
        self.assertEqual([d.doc_id for d in result], ["unknown-date", "d2", "d1", "d2"])
        self.assertIsNone(result[0].doc_dt)
        for did in ("missing", "other-box", "future"):
            self.assertIsNone(self.store.get_message("a", did, query_date=today))
        self.assertEqual(self.store.get_message("a", "future").doc_dt, date(2025, 1, 3))
        for operation in (lambda: self.store.list_messages("absent"),
                          lambda: self.store.get_message("absent", "d1"),
                          lambda: self.store.get_messages("absent", [])):
            with self.assertRaises(UnknownMailbox):
                operation()

    def test_pagination_ties_nulls_and_text(self):
        body = "  Строка\r\n'цитата'\\😀\t" + "я" * 500 + "\n "
        docs = [{"doc_id": did, "synthetic_user": "a", "doc": body, "doc_dt": dt}
                for did, dt in [("я", None), ("a", None), ("A", "2025-01-01"),
                                ("d1", "2025-01-01"), ("d2", "2025-01-02"),
                                ("future", "2025-01-03")]]
        fixture(self.path, documents=docs)
        import_corpus(self.engine, self.path)
        seen, cursor = [], None
        while True:
            page = self.store.list_messages("a", query_date=date(2025, 1, 2), limit=1, after=cursor)
            seen.extend(p.doc_id for p in page.items)
            self.assertTrue(all(p.snippet == body[:200] for p in page.items))
            cursor = page.next_cursor
            if cursor is None:
                break
        self.assertEqual(seen, ["d2", "A", "d1", "a", "я"])
        self.assertEqual(self.store.get_message("a", "я").doc, body)
        cursor = self.store.list_messages("a", limit=1).next_cursor
        with self.assertRaises(ValueError):
            self.store.list_messages("b", after=cursor)
        with self.assertRaises(ValueError):
            self.store.list_messages("a", query_date=date(2025, 1, 2), after=cursor)
        with self.assertRaises(ValueError):
            self.store.list_messages("a", limit=0)

    def test_rollback_after_inserted_batch(self):
        def fail_second_batch(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO messages"):
                fail_second_batch.count += 1
                if fail_second_batch.count == 2:
                    raise RuntimeError("injected failure after first batch")
        fail_second_batch.count = 0
        event.listen(self.engine, "before_cursor_execute", fail_second_batch)
        try:
            with self.assertRaises(RuntimeError):
                import_corpus(self.engine, self.path, batch_size=2)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_second_batch)
        with self.engine.connect() as conn:
            for table in (mailboxes, messages, corpus_import):
                self.assertEqual(conn.execute(select(table)).all(), [])
        self.assertEqual(import_corpus(self.engine, self.path)["status"], "imported")

    def test_validation_and_conflicting_corpus(self):
        import_corpus(self.engine, self.path)
        fixture(self.path, documents=[
            {"doc_id": "d1", "synthetic_user": "a", "doc": "changed", "doc_dt": None},
            {"doc_id": "d2", "synthetic_user": "a", "doc": "text", "doc_dt": None}])
        with self.assertRaisesRegex(ValidationError, "different corpus"):
            import_corpus(self.engine, self.path)
        self.assertNotEqual(self.store.get_message("a", "d1").doc, "changed")
        (self.path / "documents.jsonl").write_text("corrupt")
        with self.assertRaises(ValidationError):
            import_corpus(self.engine, self.path)

    def test_constraints_and_untracked_data(self):
        for values in ({"doc_id": "x", "synthetic_user": "absent", "doc": "text"},
                       {"doc_id": "x", "synthetic_user": "a", "doc": None}):
            with self.assertRaises(DBAPIError), self.engine.begin() as conn:
                conn.execute(messages.insert().values(**values))
        with self.engine.begin() as conn:
            conn.execute(mailboxes.insert().values(synthetic_user="a"))
        with self.assertRaisesRegex(ValidationError, "without import metadata"):
            import_corpus(self.engine, self.path)

    def test_batch_uses_one_message_query(self):
        import_corpus(self.engine, self.path)
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", record)
        try:
            self.store.get_messages("a", ["d2", "d1", "unknown-date"])
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        self.assertEqual(len(statements), 2)  # mailbox check + one batch query

    def test_concurrent_import(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: import_corpus(self.engine, self.path), range(2)))
        self.assertEqual(sorted(r["status"] for r in results), ["already_imported", "imported"])
