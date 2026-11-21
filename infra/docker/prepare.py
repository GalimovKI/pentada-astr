"""Explicit preparation only; never executed by the API entry point."""
import os
import subprocess
import sys
import time

from sqlalchemy import text
from mail_search.storage.database import database_engine


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
        commands = [
            ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
            ["mailsearch", "import-postgres", "--dataset", os.environ["SEARCH_DATASET"]],
        ]
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError
            if command[0] == "mailsearch":
                print(result.stdout, end="")
        return 0
    except Exception:
        print("Preparation failed: check database access, corpus and migrations.", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
