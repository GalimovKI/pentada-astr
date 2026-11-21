"""Real PostgreSQL only; creates and drops only randomly named test databases."""
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from mail_search.storage.database import database_engine
from mail_search.storage.repository import MailStore
from tests.fixtures.dataset import fixture


@unittest.skipUnless(os.environ.get("TEST_DATABASE_ADMIN_URL"),
                     "Set TEST_DATABASE_ADMIN_URL (PostgreSQL role with CREATEDB)")
class PostgreSQLTestCase(unittest.TestCase):
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

