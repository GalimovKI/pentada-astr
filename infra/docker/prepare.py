"""Explicit preparation only; never executed by the API entry point."""
import os
import subprocess
import sys
import time

from sqlalchemy import text
from mail_search.storage.database import database_engine


def import_corpus(url, path):
    env = {**os.environ, "DATABASE_URL": url}
    for command in (["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
                    ["mailsearch", "import-postgres", "--dataset", path]):
        subprocess.run(command, env=env, capture_output=True, check=True)


def main():
    engine = None
    try:
        engine = database_engine()
        deadline = time.monotonic() + 90
        while True:
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError from None
                time.sleep(2)
        # Capture diagnostics: migration/driver tracebacks may expose credentials.
        import_corpus(os.environ["DATABASE_URL"], os.environ["SEARCH_DATASET"])
        if os.environ.get("PREPARE_ENRONQA") == "true":
            directory = os.environ["ENRONQA_DIRECTORY"]
            for lang in ("ru", "en"):
                name = f"enronqa_{lang}"
                url = engine.url.set(database=name)
                if name == engine.url.database:
                    raise ValueError("Benchmark database conflicts with the mail database")
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                    if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}):
                        conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
                import_corpus(url.render_as_string(hide_password=False), f"{directory}/enronqa-{lang}-{lang}.zip")
        return 0
    except Exception:
        print("Preparation failed: check database access, corpus and migrations.", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
