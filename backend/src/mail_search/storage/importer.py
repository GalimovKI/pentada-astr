"""Validated, atomic, append-once corpus import."""
from dataclasses import asdict

from sqlalchemy import select, text

from ..core.errors import ValidationError
from ..ingestion.dataset import load_dataset
from .schema import corpus_import, mailboxes, messages


def import_corpus(engine, path, *, batch_size=500):
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    dataset = load_dataset(path)  # Validate before opening a write transaction.
    summary = dataset.summary
    result = dict(fingerprint=summary["fingerprint"], mailboxes=summary["mailboxes"],
                  messages=summary["documents"], unknown_dates=summary["unknown_document_dates"])
    with engine.begin() as connection:
        # Serialize importers, including the initially empty database. Locks also
        # exclude concurrent manual writes until the import commits or rolls back.
        connection.execute(text("LOCK TABLE corpus_import, mailboxes, messages IN EXCLUSIVE MODE"))
        existing = connection.execute(select(corpus_import)).mappings().first()
        if existing:
            if existing["fingerprint"] != result["fingerprint"]:
                raise ValidationError("Database already contains a different corpus; use a separate database")
            return dict(result, status="already_imported")
        if (connection.execute(select(messages.c.doc_id).limit(1)).first()
                or connection.execute(select(mailboxes.c.synthetic_user).limit(1)).first()):
            raise ValidationError("Database has data without import metadata; use a separate database")
        users = sorted({d.synthetic_user for d in dataset.documents.values()})
        connection.execute(mailboxes.insert(), [{"synthetic_user": u} for u in users])
        documents = list(dataset.documents.values())
        for start in range(0, len(documents), batch_size):
            connection.execute(messages.insert(),
                               [asdict(d) for d in documents[start:start + batch_size]])
        connection.execute(corpus_import.insert().values(id=1, format_version=1, **result))
    return dict(result, status="imported")
